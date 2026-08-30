#!/usr/bin/env bash
#
# Proves, against a real Android device, that the local database is encrypted
# at rest (encryption envelope §14).
#
# The unit tests in shared/core assert the same properties, and they assert them
# about a database this repository's own code created on a laptop. This script
# asserts them about the file sitting in /data/data on a device, put there by
# the installed APK — which is the artifact an adversary actually gets hold of.
# The two are not the same claim, and only the second one answers "what does a
# seized phone give up".
#
# It is also how the two bugs in the first cut of §14 were found: the Android
# migration could not create its ATTACH target, and the failing statement wrote
# the database key into logcat. Neither showed up on a laptop.
#
# Usage:
#   scripts/prove_local_encryption.sh [serial]
#
# Requires: adb, a connected device or emulator, a debuggable build (run-as
# needs one). Writes nothing to the repository.

set -euo pipefail

PACKAGE="com.amr.data_collection_lab"
NEEDLE="ZEBRAQUARTZ_PROOF_ANSWER"
SERIAL="${1:-}"
ADB=(adb)
[[ -n "$SERIAL" ]] && ADB=(adb -s "$SERIAL")

# Every adb call gets its stdin from /dev/null. `adb shell` forwards stdin to
# the device and drains it, so without this the first one swallows whatever is
# waiting for the prompt in step 5 and `read` then sees EOF.
adb_() { "${ADB[@]}" "$@" </dev/null; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail() { printf '\n  FAILED: %s\n' "$*" >&2; exit 1; }
ok() { printf '  ok   %s\n' "$*"; }

echo "Local database encryption, on device (encryption envelope §14)"
echo

adb_ shell "pm list packages | grep -qx package:$PACKAGE" \
  || fail "$PACKAGE is not installed. ./gradlew :clients:androidApp:installDebug"

# ---------------------------------------------------------------------------
echo "1. The app has been run and has a database"
adb_ shell run-as "$PACKAGE" ls databases/dcp.db >/dev/null 2>&1 \
  || fail "no databases/dcp.db — open the app once first"
adb_ exec-out run-as "$PACKAGE" cat databases/dcp.db > "$work/dcp.db"
ok "pulled $(wc -c < "$work/dcp.db" | tr -d ' ') bytes"

# ---------------------------------------------------------------------------
echo
echo "2. The file does not begin with the cleartext SQLite header"
header=$(head -c 16 "$work/dcp.db" | LC_ALL=C tr -d '\000')
if [[ "$header" == "SQLite format 3" ]]; then
  fail "the header is 'SQLite format 3' — this database is not encrypted"
fi
ok "header is not 'SQLite format 3' (SQLCipher's salt occupies those bytes)"

# ---------------------------------------------------------------------------
echo
echo "3. sqlite3 cannot open it without a key"
if command -v sqlite3 >/dev/null; then
  if sqlite3 "$work/dcp.db" "select count(*) from sqlite_master;" >/dev/null 2>&1; then
    fail "sqlite3 opened it with no key"
  fi
  ok "sqlite3 refuses it: not a database"
else
  echo "  skip  sqlite3 not installed"
fi

# ---------------------------------------------------------------------------
echo
echo "4. Nothing readable is in the file"
# Schema text is the giveaway that needs no knowledge of the data: every plain
# SQLite file carries its CREATE TABLE statements in the clear.
for needle in "CREATE TABLE" "op_outbox" "value_json"; do
  if LC_ALL=C grep -a -q "$needle" "$work/dcp.db"; then
    fail "found '$needle' in the raw file"
  fi
done
ok "no schema text, no column names"

# ---------------------------------------------------------------------------
echo
echo "5. An answer typed into the app does not appear in the file"
echo "   Type '$NEEDLE' into any text question, leave the page so the op is"
echo "   written, then press return here."
read -r _ < /dev/tty 2>/dev/null || read -r _ || true
adb_ shell am force-stop "$PACKAGE"
sleep 1
adb_ exec-out run-as "$PACKAGE" cat databases/dcp.db > "$work/after.db"
if LC_ALL=C grep -a -q "$NEEDLE" "$work/after.db"; then
  fail "the answer is readable in the raw database file"
fi
ok "the answer is not in databases/dcp.db"

# Every other file the app owns, not just the database: the -wal is where the
# newest pages live before a checkpoint, and it is what a check that looked only
# at dcp.db would miss.
for path in $(adb_ shell run-as "$PACKAGE" find . -type f 2>/dev/null | tr -d '\r'); do
  adb_ exec-out run-as "$PACKAGE" cat "$path" > "$work/candidate" 2>/dev/null || continue
  if LC_ALL=C grep -a -q "$NEEDLE" "$work/candidate"; then
    fail "the answer is readable in $path"
  fi
done
ok "the answer is in none of the app's files"

# ---------------------------------------------------------------------------
echo
echo "6. The key is in no file the app owns (§14.4: it never leaves the Keystore)"
# There is no key to search for — it is derived inside the Android Keystore and
# never materialises outside the process. So the check is structural: nothing
# that stores key-shaped blobs may exist.
prefs=$(adb_ shell run-as "$PACKAGE" ls shared_prefs 2>/dev/null | tr -d '\r' || true)
[[ -z "$prefs" ]] || fail "shared_prefs exists and may hold key material: $prefs"
ok "no shared_prefs at all"

# ---------------------------------------------------------------------------
echo
echo "7. The key never reached the log (§14.5)"
if adb_ logcat -d | LC_ALL=C grep -qiE "x'[0-9a-f]{64}'|PRAGMA +key"; then
  fail "a 64-hex key literal or a PRAGMA key statement is in logcat"
fi
ok "no key literal in logcat"

echo
echo "All checks passed."
