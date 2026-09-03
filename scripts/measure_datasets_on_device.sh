#!/usr/bin/env bash
#
# What a real dataset costs on a real phone (Form IR §3.2, §12; item 4 part 5).
#
# §3.2 states a performance contract — resolution proportional to the rows
# matching the selector, never to the dataset — and `StoredDatasetSource`
# currently reads a whole version out of SQLCipher and filters in memory.
# Whether that is good enough is not a question a laptop can answer. The target
# is a handset with 2 GB of RAM holding 38,000 villages, and the number this
# prints is the one that decides whether the feature is usable in a village.
#
# It is meant to be run and *published* whatever it says. If per-keystroke
# filtering is not viable, the honest outcome is a stated limit in §3.2 and an
# index on StoredDatasetSource — not a feature called done that a customer
# discovers in the field.
#
# Usage:
#   scripts/measure_datasets_on_device.sh [rows] [serial]
#
# Requires: adb, a connected device, a debug build (BenchmarkActivity exists in
# no release build — it writes tens of thousands of rows into the app's real
# database). Writes nothing to the repository.

set -euo pipefail

PACKAGE="com.amr.data_collection_lab"
ROWS="${1:-38000}"
SERIAL="${2:-}"
ADB=(adb)
[[ -n "$SERIAL" ]] && ADB=(adb -s "$SERIAL")
command -v adb >/dev/null || ADB=("$HOME/Library/Android/sdk/platform-tools/adb")
[[ -n "$SERIAL" ]] && ADB=("${ADB[0]}" -s "$SERIAL")

adb_() { "${ADB[@]}" "$@" </dev/null; }

echo "Dataset cost on device — $ROWS rows (Form IR §3.2)"
echo

adb_ shell "pm list packages | grep -qx package:$PACKAGE" \
  || { echo "  $PACKAGE is not installed. ./gradlew :clients:androidApp:installDebug" >&2; exit 1; }

model=$(adb_ shell getprop ro.product.model | tr -d '\r')
mem=$(adb_ shell cat /proc/meminfo | head -1 | tr -d '\r')
echo "  device: $model    $mem"
echo

adb_ logcat -c
adb_ shell am start -n "$PACKAGE/.BenchmarkActivity" \
  --ei rows "$ROWS" --ei districts 180 >/dev/null

# The activity logs DONE last, whether it succeeded or threw.
deadline=$(( $(date +%s) + 600 ))
while (( $(date +%s) < deadline )); do
  if adb_ logcat -d -s DCP_BENCH:* | grep -q "DONE"; then break; fi
  sleep 2
done

output=$(adb_ logcat -d -s DCP_BENCH:*)
if grep -q "FAILED" <<<"$output"; then
  echo "$output" | sed -n 's/.*DCP_BENCH: //p'
  echo >&2
  echo "  the benchmark threw — see above" >&2
  exit 1
fi
if ! grep -q "DONE" <<<"$output"; then
  echo "  timed out after 10 minutes with no DONE. Partial log:" >&2
  echo "$output" | sed -n 's/.*DCP_BENCH: //p' >&2
  exit 1
fi

echo "$output" | sed -n 's/.*DCP_BENCH: RESULT /  /p'
echo
echo "  Read these against §3.2: filter_first_ms is what the first keystroke on"
echo "  a question costs, because the source parses a whole version into memory"
echo "  on first use; filter_median_ms is every keystroke after. delta_apply_ms"
echo "  is the second-sync path, which is what happens every week for the life"
echo "  of the project."
