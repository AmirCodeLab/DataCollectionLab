package com.dcp.core.sync

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement

/** Wire types for /api/v1/sync (specs/sync-protocol-v0.1.md §2, §4, §5). */

val SyncJson: Json = Json {
    ignoreUnknownKeys = true
    encodeDefaults = true
}

@Serializable
data class WireOp(
    val opId: String,
    val submissionId: String,
    val formId: String,
    val formVersion: Int,
    val kind: String,
    val path: String? = null,
    val value: JsonElement? = null,
    // Encrypted ops (sync §2.1). Present together, and never beside `value` —
    // the server rejects an op carrying both as malformed. Lowercase hex.
    val valueCiphertext: String? = null,
    val contentKeyId: String? = null,
    val nonce: String? = null,
    val deviceId: String,
    val actorId: String? = null,
    val counter: Long,
    val wallClock: String,
)

/** One wrap of a content key to one recipient project key (envelope §4.3). */
@Serializable
data class WireWrappedKey(
    val projectKeyId: String,
    val ephemeralPublic: String,
    val nonce: String,
    val wrappedKey: String,
)

/**
 * A content key, in the only form that ever leaves the device: wrapped copies.
 *
 * Rides the push rather than a separate call so a key and the first ops it
 * encrypts commit in one transaction (sync §4) — uploading them separately
 * would let a device die between the two and leave ops nobody can decrypt.
 */
@Serializable
data class WireContentKey(
    val contentKeyId: String,
    val submissionId: String,
    val deviceId: String,
    val wraps: List<WireWrappedKey>,
)

@Serializable
data class WirePushRequest(
    val deviceId: String,
    val ops: List<WireOp>,
    val keys: List<WireContentKey> = emptyList(),
)

/**
 * GET /api/v1/devices/{deviceId}/crypto (sync §4): the project's security mode
 * and the public keys to wrap content keys to. Public keys only.
 */
@Serializable
data class WireProjectKey(
    val keyId: String,
    val publicKey: String,
    val role: String,
    val label: String = "",
)

@Serializable
data class WireDeviceCryptoResponse(
    val deviceId: String,
    val projectId: String,
    val securityMode: String,
    val projectKeys: List<WireProjectKey> = emptyList(),
)

/**
 * POST /api/v1/devices (sync §4). Idempotent: registering an id the server
 * already knows returns `already_registered`, which is success.
 */
@Serializable
data class WireDeviceRegisterRequest(
    val deviceId: String,
    val platform: String,
    val osVersion: String? = null,
    val appVersion: String? = null,
)

@Serializable
data class WireDeviceRegisterResponse(
    val deviceId: String,
    val status: String,
)

/**
 * Body of a failed registration. `reason` is the contract — project_not_found,
 * project_ambiguous, project_mismatch, device_revoked — and `message` says what
 * to do about it. Reported verbatim so a developer sees "the database was never
 * seeded" rather than a bare status code.
 */
@Serializable
data class WireErrorDetail(
    val reason: String,
    val message: String = "",
)

@Serializable
data class WireErrorBody(val detail: WireErrorDetail? = null)

@Serializable
data class WireRejectedOp(val opId: String? = null, val reason: String)

@Serializable
data class WirePushResponse(
    val accepted: List<String> = emptyList(),
    val rejected: List<WireRejectedOp> = emptyList(),
    val serverCursor: Long = 0,
)

@Serializable
data class WirePulledOp(
    val opId: String,
    val submissionId: String,
    val formId: String,
    val formVersion: Int,
    val kind: String,
    val path: String? = null,
    val value: JsonElement? = null,
    // Relayed byte-for-byte from whichever device pushed it; the server has no
    // key for these and never had one.
    val valueCiphertext: String? = null,
    val contentKeyId: String? = null,
    val nonce: String? = null,
    val deviceId: String,
    val actorId: String? = null,
    val counter: Long,
    val wallClock: String,
    val serverSeq: Long,
)

/**
 * One entry of the form manifest (sync §5, `scope=forms`). Names a version and
 * what it hashes to; the document itself is fetched separately, so a pull costs
 * a few hundred bytes rather than every form on the phone.
 */
@Serializable
data class WireDeployedFormVersion(
    val formVersionId: String,
    val formId: String,
    val version: Int,
    val title: String,
    val irChecksum: String,
    val deployedAt: String,
)

@Serializable
data class WirePullResponse(
    val ops: List<WirePulledOp> = emptyList(),
    // Tombstones are carried but not applied yet — repeat/submission deletion
    // has no local handling in this slice.
    val tombstones: List<JsonElement> = emptyList(),
    // Null and empty are DIFFERENT answers, which is why this is nullable
    // rather than defaulted to an empty list.
    //
    // Null: the field was absent — this request did not ask for `scope=forms`,
    // or the server predates form delivery. Nothing has been said about this
    // device's forms and the device must leave them exactly as they are.
    //
    // Empty: the server answered, and this environment deploys nothing. That is
    // a real statement and the device acts on it.
    //
    // Collapsing the two would mean either undeploying every form on the device
    // whenever it syncs against an older server, or never being able to notice a
    // project that withdrew its last form.
    val forms: List<WireDeployedFormVersion>? = null,
    val nextCursor: Long,
    val hasMore: Boolean = false,
)

/**
 * GET /api/v1/forms/versions/{formVersionId} — one published version and its
 * Form IR. Immutable, so a device may cache it forever.
 */
@Serializable
data class WireFormVersionDocument(
    val formVersionId: String,
    val formId: String,
    val version: Int,
    val title: String,
    val irChecksum: String,
    val form: JsonElement,
)

/**
 * GET /health — the one endpoint that needs no device and no project, which is
 * what makes it the right target for a reachability check (see
 * [SyncClient.checkConnection]).
 *
 * `environment` is the deployment's own name for itself. It is here because the
 * failure a reachability check cannot otherwise see is the one where everything
 * works and the address is wrong: a phone pointed at staging syncs perfectly
 * and files a morning's interviews where nobody is looking for them.
 */
@Serializable
data class WireHealth(
    val status: String,
    val environment: String,
)

/**
 * What one form refresh managed (sync §5).
 *
 * [undelivered] is the half that used to be thrown away. A manifest entry whose
 * document will not fetch is skipped rather than abandoning the batch — one
 * unreachable form must not cost the device the others — but a skip that is
 * not reported leaves the device holding no form, the sync reporting success,
 * and nothing anywhere saying why.
 */
internal data class FormRefresh(val fetched: Int, val undelivered: List<String>)
