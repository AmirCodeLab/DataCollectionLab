package com.dcp.core.security

import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

/**
 * The desktop OS's own secret store, which is where the local database key
 * lives on desktop (encryption envelope §14.4).
 *
 * Deliberately an interface with no default implementation. There is no
 * file-backed variant and there must not be one: a key in a file under the
 * user's home is the exact artifact §14.3 refuses to create, and the moment one
 * exists it becomes the path every awkward environment takes.
 *
 * Each implementation shells out to the platform's own tool rather than
 * binding its C API through JNI. That is a real trade — a subprocess per read,
 * and a dependency on a binary being installed — bought for one thing: **the
 * secret never travels in a command line.** `argv` is world-readable through
 * `ps` for the life of the process, so every implementation here passes the
 * secret over the child's stdin and reads it back over stdout.
 */
interface CredentialStore {

    /** For error messages, so a failure says which store refused. */
    val description: String

    /** The stored secret, or null if there is none. */
    fun read(service: String, account: String): ByteArray?

    /** Stores [secret], replacing any existing entry. */
    fun write(service: String, account: String, secret: ByteArray)

    /** Removes the entry if it exists. Not an error if it does not. */
    fun delete(service: String, account: String)

    companion object {
        /**
         * The credential store for the running OS.
         *
         * @throws DatabaseKeyUnavailable on an OS with no implementation here,
         *   rather than degrading to something weaker.
         */
        fun forCurrentOs(): CredentialStore {
            val os = System.getProperty("os.name").orEmpty().lowercase()
            return when {
                os.contains("mac") || os.contains("darwin") -> MacKeychainCredentialStore()
                os.contains("win") -> WindowsCredentialManagerStore()
                os.contains("linux") || os.contains("nix") || os.contains("nux") ->
                    SecretServiceCredentialStore()

                else -> throw DatabaseKeyUnavailable(
                    "no OS credential store is implemented for \"${System.getProperty("os.name")}\", " +
                        "and encryption envelope §14.5 forbids falling back to an unencrypted " +
                        "database or to a key in a file.",
                )
            }
        }
    }
}

/**
 * Runs [command], writing [stdin] to the child and returning its stdout.
 *
 * [stdin] is the secret's only route into the child process, and the returned
 * bytes are its only route out. Neither ever appears in [command].
 */
internal fun runCapturing(
    command: List<String>,
    stdin: ByteArray? = null,
    timeoutSeconds: Long = DEFAULT_TIMEOUT_SECONDS,
): ProcessResult {
    val process = ProcessBuilder(command)
        .redirectErrorStream(false)
        .start()

    // Both pipes are drained on their own threads and the wait is bounded.
    //
    // Reading either pipe on this thread would make the timeout below
    // unreachable — a read blocks until the child writes or exits, and these
    // tools have a mode where it does neither: `security(1)` against a locked
    // keychain sits waiting on an interactive prompt. The first draft of this
    // hung a test run for ten minutes on exactly that.
    var stdoutBytes = ByteArray(0)
    var stderrBytes = ByteArray(0)
    val drains = listOf(
        Thread { stdoutBytes = process.inputStream.use { it.readAllBytesCompat() } },
        Thread { stderrBytes = process.errorStream.use { it.readAllBytesCompat() } },
    ).onEach { it.isDaemon = true; it.start() }

    process.outputStream.use { out ->
        if (stdin != null) out.write(stdin)
        out.flush()
    }

    if (!process.waitFor(timeoutSeconds, TimeUnit.SECONDS)) {
        process.destroyForcibly()
        throw DatabaseKeyUnavailable(
            "${command.first()} did not finish within ${timeoutSeconds}s. If it was waiting on " +
                "a keychain prompt, unlock the store and start the app again.",
        )
    }
    drains.forEach { it.join(TimeUnit.SECONDS.toMillis(5)) }

    return ProcessResult(process.exitValue(), stdoutBytes, String(stderrBytes).trim())
}

/**
 * Long enough for a person to answer a keychain or keyring prompt — that prompt
 * *is* the desktop app lock of §14.7 — and short enough that an app which will
 * never get an answer says so instead of hanging.
 */
private const val DEFAULT_TIMEOUT_SECONDS = 120L

internal class ProcessResult(val exitCode: Int, val stdout: ByteArray, val stderr: String)

private fun java.io.InputStream.readAllBytesCompat(): ByteArray {
    val buffer = ByteArrayOutputStream()
    copyTo(buffer)
    return buffer.toByteArray()
}

/** Hex, because every one of these stores takes a string, not a blob. */
internal fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }

internal fun String.hexToBytes(): ByteArray {
    val clean = trim()
    require(clean.length % 2 == 0) { "not hex: odd length" }
    return ByteArray(clean.length / 2) {
        clean.substring(it * 2, it * 2 + 2).toInt(16).toByte()
    }
}

/**
 * macOS: the login Keychain, through `security(1)`.
 *
 * `security -i` reads its *commands* from stdin, so the secret is written to
 * the pipe rather than passed as `-w <secret>` where `ps` would show it.
 * Reading is `find-generic-password -w`, which prints only the password.
 */
internal class MacKeychainCredentialStore(
    /**
     * Which keychain to use; null means the user's default (login) keychain.
     * Only the tests pass one — they create a scratch keychain rather than
     * writing test keys into a developer's own.
     */
    private val keychain: String? = null,
) : CredentialStore {

    override val description: String get() = "macOS Keychain (security(1))"

    override fun read(service: String, account: String): ByteArray? {
        val result = runCapturing(
            listOf("security", "find-generic-password", "-s", service, "-a", account, "-w") +
                listOfNotNull(keychain),
        )
        // 44 = errSecItemNotFound. Any other failure is a real one and must not
        // be mistaken for "no key yet", which would silently mint a second key
        // and orphan the existing database.
        if (result.exitCode == 44) return null
        if (result.exitCode != 0) {
            throw DatabaseKeyUnavailable(
                "macOS Keychain lookup failed (exit ${result.exitCode}): ${result.stderr}",
            )
        }
        return String(result.stdout).trim().hexToBytes()
    }

    override fun write(service: String, account: String, secret: ByteArray) {
        // -U updates in place if the item exists. -T "" means no application is
        // pre-trusted to read it without the keychain prompting.
        val command = buildString {
            append("add-generic-password")
            append(" -s ").append(quote(service))
            append(" -a ").append(quote(account))
            append(" -D ").append(quote("DCP local database key"))
            append(" -w ").append(quote(secret.toHex()))
            append(" -U")
            keychain?.let { append(' ').append(quote(it)) }
            append('\n')
        }
        val result = runCapturing(listOf("security", "-i"), command.toByteArray())
        if (result.exitCode != 0) {
            throw DatabaseKeyUnavailable(
                "macOS Keychain store failed (exit ${result.exitCode}): ${result.stderr}",
            )
        }
    }

    override fun delete(service: String, account: String) {
        runCapturing(
            listOf("security", "delete-generic-password", "-s", service, "-a", account) +
                listOfNotNull(keychain),
        )
    }

    private fun quote(value: String) = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
}

/**
 * Linux: the Secret Service API (GNOME Keyring, KWallet) through
 * `secret-tool(1)`, which takes the secret on stdin and prints it on stdout.
 */
internal class SecretServiceCredentialStore : CredentialStore {

    override val description: String get() = "Secret Service (secret-tool)"

    override fun read(service: String, account: String): ByteArray? {
        val result = try {
            runCapturing(listOf("secret-tool", "lookup", "service", service, "account", account))
        } catch (e: java.io.IOException) {
            throw DatabaseKeyUnavailable(
                "secret-tool is not installed, so there is no OS credential store to hold the " +
                    "local database key. Install libsecret-tools (Debian/Ubuntu) or libsecret " +
                    "(Fedora/Arch). Encryption envelope §14.5 forbids falling back to a key in " +
                    "a file.",
                e,
            )
        }
        // secret-tool exits 1 with empty output when the item is absent.
        if (result.exitCode != 0 || result.stdout.isEmpty()) return null
        return String(result.stdout).trim().hexToBytes()
    }

    override fun write(service: String, account: String, secret: ByteArray) {
        val result = runCapturing(
            listOf(
                "secret-tool", "store", "--label=DCP local database key",
                "service", service, "account", account,
            ),
            stdin = secret.toHex().toByteArray(),
        )
        if (result.exitCode != 0) {
            throw DatabaseKeyUnavailable(
                "secret-tool store failed (exit ${result.exitCode}): ${result.stderr}",
            )
        }
    }

    override fun delete(service: String, account: String) {
        runCapturing(listOf("secret-tool", "clear", "service", service, "account", account))
    }
}

/**
 * Windows: Credential Manager, through a PowerShell shim over `CredRead` /
 * `CredWrite` / `CredDelete`.
 *
 * Credential Manager rather than DPAPI-to-a-file: `ConvertFrom-SecureString` is
 * the usual PowerShell answer and it produces a blob you then have to store
 * somewhere, which §14.3 forbids. `CredWrite` keeps it in the OS's own store,
 * protected by the user's sign-in, with nothing of ours on disk.
 *
 * **Unverified on hardware.** This machine is macOS; the macOS and Linux paths
 * above are exercised by tests and this one is not. It is written from the
 * documented API and should be run on Windows before a desktop release.
 */
internal class WindowsCredentialManagerStore : CredentialStore {

    override val description: String get() = "Windows Credential Manager (CredRead/CredWrite)"

    override fun read(service: String, account: String): ByteArray? {
        val result = powerShell(
            """
            ${'$'}t = "${target(service, account)}"
            ${'$'}c = [DcpCred]::Read(${'$'}t)
            if (${'$'}c -eq ${'$'}null) { exit 44 }
            [Console]::Out.Write(${'$'}c)
            """.trimIndent(),
        )
        if (result.exitCode == 44) return null
        if (result.exitCode != 0) {
            throw DatabaseKeyUnavailable(
                "Windows Credential Manager read failed (exit ${result.exitCode}): ${result.stderr}",
            )
        }
        return String(result.stdout).trim().hexToBytes()
    }

    override fun write(service: String, account: String, secret: ByteArray) {
        // The secret arrives on stdin, so it is in neither argv nor the script.
        val result = powerShell(
            """
            ${'$'}secret = [Console]::In.ReadToEnd().Trim()
            [DcpCred]::Write("${target(service, account)}", ${'$'}secret)
            """.trimIndent(),
            stdin = secret.toHex().toByteArray(),
        )
        if (result.exitCode != 0) {
            throw DatabaseKeyUnavailable(
                "Windows Credential Manager write failed (exit ${result.exitCode}): ${result.stderr}",
            )
        }
    }

    override fun delete(service: String, account: String) {
        powerShell("""[DcpCred]::Delete("${target(service, account)}")""")
    }

    private fun target(service: String, account: String) = "$service/$account"

    private fun powerShell(body: String, stdin: ByteArray? = null): ProcessResult =
        runCapturing(
            listOf(
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "$INTEROP\n$body",
            ),
            stdin = stdin,
        )

    private companion object {
        /**
         * CredRead/CredWrite/CredDelete via P/Invoke. CRED_TYPE_GENERIC = 1,
         * CRED_PERSIST_LOCAL_MACHINE = 2 — persisted for this user on this
         * machine and not roamed to another, matching the iOS
         * `ThisDeviceOnly` rule in §14.4.
         */
        val INTEROP = """
        Add-Type -TypeDefinition @"
        using System;
        using System.Runtime.InteropServices;
        public class DcpCred {
          [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
          private struct CREDENTIAL {
            public uint Flags; public uint Type; public string TargetName; public string Comment;
            public long LastWritten; public uint CredentialBlobSize; public IntPtr CredentialBlob;
            public uint Persist; public uint AttributeCount; public IntPtr Attributes;
            public string TargetAlias; public string UserName;
          }
          [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
          private static extern bool CredReadW(string target, uint type, uint flags, out IntPtr cred);
          [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
          private static extern bool CredWriteW(ref CREDENTIAL cred, uint flags);
          [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
          private static extern bool CredDeleteW(string target, uint type, uint flags);
          [DllImport("advapi32.dll")] private static extern void CredFree(IntPtr buffer);

          public static string Read(string target) {
            IntPtr ptr;
            if (!CredReadW(target, 1, 0, out ptr)) return null;
            try {
              CREDENTIAL c = (CREDENTIAL)Marshal.PtrToStructure(ptr, typeof(CREDENTIAL));
              byte[] blob = new byte[c.CredentialBlobSize];
              Marshal.Copy(c.CredentialBlob, blob, 0, (int)c.CredentialBlobSize);
              return System.Text.Encoding.Unicode.GetString(blob);
            } finally { CredFree(ptr); }
          }

          public static void Write(string target, string secret) {
            byte[] blob = System.Text.Encoding.Unicode.GetBytes(secret);
            IntPtr mem = Marshal.AllocHGlobal(blob.Length);
            try {
              Marshal.Copy(blob, 0, mem, blob.Length);
              CREDENTIAL c = new CREDENTIAL();
              c.Type = 1; c.TargetName = target; c.Persist = 2;
              c.CredentialBlobSize = (uint)blob.Length; c.CredentialBlob = mem;
              c.UserName = Environment.UserName;
              if (!CredWriteW(ref c, 0))
                throw new Exception("CredWrite failed: " + Marshal.GetLastWin32Error());
            } finally { Marshal.FreeHGlobal(mem); Array.Clear(blob, 0, blob.Length); }
          }

          public static void Delete(string target) { CredDeleteW(target, 1, 0); }
        }
        "@
        """.trimIndent()
    }
}
