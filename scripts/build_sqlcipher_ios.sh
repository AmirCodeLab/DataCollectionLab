#!/usr/bin/env bash
#
# Builds SQLCipher as an .xcframework for the iOS app to link instead of the
# SDK's libsqlite3 (encryption envelope §14).
#
# Why this exists at all. Android and desktop get their cipher from a Gradle
# dependency; iOS cannot. Kotlin/Native compiles SQLiter's cinterop against the
# SDK's sqlite3 headers and leaves the `sqlite3_*` symbols to be resolved when
# Xcode links the app. Whatever provides them at that point is the SQLite the
# app runs. Today that is `-lsqlite3` in Config.xcconfig, which has no cipher —
# and against plain SQLite `PRAGMA key` is an unrecognised pragma that SQLite
# ignores without an error, so the app runs perfectly and writes every answer to
# disk in the clear. That is the exact failure §14.5 exists for, and the reason
# DatabaseDriverFactory checks the file header after opening rather than
# trusting that the pragma did anything.
#
# CommonCrypto rather than OpenSSL: SQLCipher supports Apple's own crypto
# library (-DSQLCIPHER_CRYPTO_CC), which removes a large third-party dependency
# and an iOS OpenSSL build from the chain. The cipher and the file format are
# identical either way.
#
# Usage:
#   scripts/build_sqlcipher_ios.sh [version]
#
# Output:
#   clients/iosApp/Frameworks/SQLCipher.xcframework   (device + simulator)
#
# Config.xcconfig already links it: LIBRARY_SEARCH_PATHS is set per SDK so the
# right slice is found, and `-lsqlite3` is gone. Until this script has been run
# at least once the iOS link fails with "library not found for -lsqlcipher",
# which is the correct failure — the alternative was an app that linked the
# system SQLite and silently stored cleartext.
#
# The build artifact is deliberately NOT committed. It is ~3 MB of compiled C
# per slice, it is reproducible from this script, and a binary blob in the
# repository is a supply-chain question nobody wants to answer at review time.

set -euo pipefail

VERSION="${1:-v4.6.1}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$REPO_ROOT/clients/iosApp/Frameworks"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

command -v xcodebuild >/dev/null || {
  echo "xcodebuild not found. Xcode (not just the Command Line Tools) is required." >&2
  echo "If Xcode is installed: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer" >&2
  exit 1
}

echo "Building SQLCipher $VERSION for iOS"
git clone --depth 1 --branch "$VERSION" https://github.com/sqlcipher/sqlcipher.git "$WORK/src"

cd "$WORK/src"
# Generates sqlite3.c/sqlite3.h with the codec compiled in. The configure step
# needs a host compiler; the cross-compilation happens below, per slice.
./configure --with-crypto-lib=commoncrypto --enable-tempstore=yes \
  CFLAGS="-DSQLITE_HAS_CODEC -DSQLCIPHER_CRYPTO_CC" >/dev/null
make sqlite3.c >/dev/null

# The same flags SQLCipher's own iOS builds use. SQLITE_TEMP_STORE=2 keeps
# temporary tables in memory: a temp table spilled to disk is plaintext sitting
# beside an encrypted database, which would quietly undo the whole exercise.
CFLAGS_COMMON=(
  -DSQLITE_HAS_CODEC
  -DSQLCIPHER_CRYPTO_CC
  -DSQLITE_TEMP_STORE=2
  -DSQLITE_THREADSAFE=1
  -DSQLITE_ENABLE_FTS5
  -DSQLITE_ENABLE_JSON1
  -DSQLITE_ENABLE_RTREE
  -DNDEBUG
  -O2
)

build_slice() {
  local name="$1" sdk="$2" target="$3"
  local dir="$WORK/$name"
  mkdir -p "$dir"
  local sysroot
  sysroot="$(xcrun --sdk "$sdk" --show-sdk-path)"
  echo "  $name ($target)"
  xcrun --sdk "$sdk" clang -c sqlite3.c -o "$dir/sqlite3.o" \
    -isysroot "$sysroot" -target "$target" \
    "${CFLAGS_COMMON[@]}"
  xcrun --sdk "$sdk" libtool -static -o "$dir/libsqlcipher.a" "$dir/sqlite3.o"
  mkdir -p "$dir/Headers"
  cp sqlite3.h "$dir/Headers/"
}

echo "Compiling slices"
build_slice device iphoneos arm64-apple-ios13.0
build_slice simulator iphonesimulator arm64-apple-ios13.0-simulator

rm -rf "$OUT_DIR/SQLCipher.xcframework"
mkdir -p "$OUT_DIR"
xcodebuild -create-xcframework \
  -library "$WORK/device/libsqlcipher.a" -headers "$WORK/device/Headers" \
  -library "$WORK/simulator/libsqlcipher.a" -headers "$WORK/simulator/Headers" \
  -output "$OUT_DIR/SQLCipher.xcframework" >/dev/null

cat <<'EOF'

Built clients/iosApp/Frameworks/SQLCipher.xcframework

clients/iosApp/Configuration/Config.xcconfig already points at it — the
per-SDK LIBRARY_SEARCH_PATHS pick the right slice, so nothing has to be added
to the Xcode project. Just build.

If the app starts and then stops with "This build cannot encrypt its local
storage", the link line still reaches the system SQLite. Check that -lsqlite3
is gone from OTHER_LDFLAGS: with both on the line, sqlite3_* resolves against
whichever the linker reaches first, and the system one gives an app that runs
happily with an unencrypted database. That refusal is the header check in
DatabaseDriverFactory doing its job (encryption envelope §14.5) — the point of
it is that this mistake is loud instead of invisible.
EOF
