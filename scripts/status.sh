#!/bin/sh
# status.sh — report real project state from the repo, not from anyone's memory.
#
# POSIX sh. Needs only git, find and grep, plus the project toolchains to run
# the test suites. Never exits nonzero because a suite failed — it reports and
# continues.

ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -n "$ROOT" ] || ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1

hr() { printf '\n== %s ==\n' "$1"; }
item() { printf '  %-24s %-12s %s\n' "$1" "$2" "$3"; }

# ---------------------------------------------------------------------------
hr "1. Conformance"

VECTORS=$(find conformance/vectors -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
printf '  vectors on disk:  %s\n' "$VECTORS"

if [ -x "$ROOT/backend/.venv/bin/python" ]; then
    PY="$ROOT/backend/.venv/bin/python"
else
    PY=python3
fi

# -k test_vector runs exactly one test per vector, nothing else.
PY_OUT=$(cd backend && "$PY" -m pytest tests/test_conformance.py -q -k test_vector 2>&1)
PY_STATUS=$?
PY_PASSED=$(printf '%s\n' "$PY_OUT" | grep -o '[0-9]* passed' | grep -o '[0-9]*' | head -1)
PY_FAILED=$(printf '%s\n' "$PY_OUT" | grep -o '[0-9]* failed' | grep -o '[0-9]*' | head -1)
[ -n "$PY_PASSED" ] || PY_PASSED=0
[ -n "$PY_FAILED" ] || PY_FAILED=0
PY_RAN=$((PY_PASSED + PY_FAILED))
if [ "$PY_STATUS" -eq 0 ]; then
    printf '  python engine:    PASS  (%s/%s vectors)\n' "$PY_PASSED" "$VECTORS"
else
    printf '  python engine:    FAIL  (%s passed, %s failed)\n' "$PY_PASSED" "$PY_FAILED"
    printf '%s\n' "$PY_OUT" | tail -5 | sed 's/^/    | /'
fi

# Clear previous results first. Stale XML from a renamed or deleted test class
# would otherwise be counted alongside the current run and inflate the totals.
KT_DIR_PRE=shared/form-engine/build/test-results/jvmTest
rm -rf "$KT_DIR_PRE"

KT_OUT=$(./gradlew :shared:form-engine:jvmTest --rerun-tasks 2>&1)
KT_STATUS=$?
# Match on the file pattern, not one hardcoded class name: renaming or moving
# the test class must not make the script report a phantom failure. Sensitivity
# and document shape are SEPARATE vector sets with their own runners and their
# own counts below — counting them here would inflate the form-vector total and
# raise a phantom "engines disagree" alarm. Every new *ConformanceTest over a
# separate set has to be excluded here too.
KT_DIR=shared/form-engine/build/test-results/jvmTest
KT_XMLS=$(find "$KT_DIR" -name 'TEST-*Conformance*.xml' \
    ! -name '*Sensitivity*' ! -name '*Malformed*' 2>/dev/null)
KT_RAN=0
KT_FAILED=0
if [ -n "$KT_XMLS" ]; then
    KT_RAN=$(grep -ho 'tests="[0-9]*"' $KT_XMLS | grep -o '[0-9]*' | awk '{s+=$1} END {print s+0}')
    KT_FAILED=$(grep -ho 'failures="[0-9]*"' $KT_XMLS | grep -o '[0-9]*' | awk '{s+=$1} END {print s+0}')
    KT_ERRORS=$(grep -ho 'errors="[0-9]*"' $KT_XMLS | grep -o '[0-9]*' | awk '{s+=$1} END {print s+0}')
    KT_FAILED=$((KT_FAILED + KT_ERRORS))
else
    printf '  kotlin engine:    no TEST-*Conformance*.xml under %s\n' "$KT_DIR"
    printf '                    (test class renamed, or the task did not run)\n'
fi
if [ "$KT_STATUS" -eq 0 ] && [ -n "$KT_XMLS" ]; then
    printf '  kotlin engine:    PASS  (%s/%s vectors)\n' "$KT_RAN" "$VECTORS"
else
    printf '  kotlin engine:    FAIL  (%s ran, %s failed)\n' "$KT_RAN" "$KT_FAILED"
    printf '%s\n' "$KT_OUT" | grep -E 'FAILED|error:' | head -5 | sed 's/^/    | /'
fi

if [ "$PY_RAN" -ne "$VECTORS" ] || [ "$KT_RAN" -ne "$VECTORS" ]; then
    printf '\n  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n'
    printf '  !! ENGINES DISAGREE ON VECTOR COUNT                   !!\n'
    printf '  !! disk=%s  python ran=%s  kotlin ran=%s\n' "$VECTORS" "$PY_RAN" "$KT_RAN"
    printf '  !! A vector missing from one engine is a release      !!\n'
    printf '  !! blocker, never a platform difference (docs/project-conventions.md).  !!\n'
    printf '  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n'
fi

# --- crypto conformance ----------------------------------------------------
# Separate vector set with its own runners on both sides. Reported separately
# because a green form suite says nothing about the crypto suite.

CRYPTO_VECTORS=$(find conformance/crypto -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
CRYPTO_GREEN=true

if [ "$CRYPTO_VECTORS" -gt 0 ]; then
    printf '\n  crypto vectors:   %s\n' "$CRYPTO_VECTORS"

    CPY_OUT=$(cd backend && "$PY" -m pytest tests/test_crypto_conformance.py -q 2>&1)
    CPY_STATUS=$?
    CPY_PASSED=$(printf '%s\n' "$CPY_OUT" | grep -o '[0-9]* passed' | grep -o '[0-9]*' | head -1)
    [ -n "$CPY_PASSED" ] || CPY_PASSED=0
    if [ "$CPY_STATUS" -eq 0 ]; then
        printf '  python crypto:    PASS  (%s/%s vectors)\n' "$CPY_PASSED" "$CRYPTO_VECTORS"
    else
        printf '  python crypto:    FAIL\n'
        printf '%s\n' "$CPY_OUT" | tail -4 | sed 's/^/    | /'
        CRYPTO_GREEN=false
    fi

    CKT_DIR=shared/core/build/test-results/jvmTest
    rm -rf "$CKT_DIR"
    CKT_OUT=$(./gradlew :shared:core:jvmTest --rerun-tasks 2>&1)
    CKT_STATUS=$?
    # The crypto vector runner only. The rest of shared/core's suite is green
    # or not on its own merits; counting it here would report a number that
    # looks like vector coverage and is not.
    CKT_XMLS=$(find "$CKT_DIR" -name 'TEST-*CryptoConformance*.xml' 2>/dev/null)
    CKT_RAN=0
    if [ -n "$CKT_XMLS" ]; then
        CKT_RAN=$(grep -ho 'tests="[0-9]*"' $CKT_XMLS | grep -o '[0-9]*' | awk '{s+=$1} END {print s+0}')
    fi
    if [ "$CKT_STATUS" -eq 0 ] && [ "$CKT_RAN" -eq "$CRYPTO_VECTORS" ]; then
        printf '  kotlin crypto:    PASS  (%s/%s vectors)\n' "$CKT_RAN" "$CRYPTO_VECTORS"
    else
        printf '  kotlin crypto:    FAIL  (%s ran)\n' "$CKT_RAN"
        printf '%s\n' "$CKT_OUT" | grep -E 'FAILED|error:' | head -4 | sed 's/^/    | /'
        CRYPTO_GREEN=false
    fi

    # A crypto suite that runs on only one side proves nothing: the vectors
    # would just be one implementation agreeing with itself.
    if [ "$CPY_PASSED" -eq 0 ] || [ "$CKT_RAN" -eq 0 ]; then
        printf '\n  !! CRYPTO VECTORS RUN ON ONLY ONE ENGINE                !!\n'
        printf '  !! Cross-engine agreement is unproven.                  !!\n'
        CRYPTO_GREEN=false
    fi
else
    printf '\n  crypto vectors:   none found in conformance/crypto\n'
    CRYPTO_GREEN=false
fi

# --- sensitivity propagation -----------------------------------------------
# The publish-time check from Form IR §10 / envelope §5.2, on both engines. A
# form that publishes on one and is refused on the other is a release blocker:
# a form author would meet a refusal their builder told them was not there.

SENS_VECTORS=$(find conformance/sensitivity -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
SENSITIVITY_GREEN=true

if [ "$SENS_VECTORS" -gt 0 ]; then
    printf '\n  sensitivity:      %s vectors\n' "$SENS_VECTORS"

    SPY_OUT=$(cd backend && "$PY" -m pytest tests/test_sensitivity_conformance.py -q 2>&1)
    SPY_STATUS=$?
    if [ "$SPY_STATUS" -eq 0 ]; then
        printf '  python sensitivity: PASS\n'
    else
        printf '  python sensitivity: FAIL\n'
        printf '%s\n' "$SPY_OUT" | tail -4 | sed 's/^/    | /'
        SENSITIVITY_GREEN=false
    fi

    SKT_XML=shared/form-engine/build/test-results/jvmTest/TEST-com.dcp.form.SensitivityConformanceTest.xml
    SKT_RAN=0
    if [ -f "$SKT_XML" ]; then
        SKT_RAN=$(grep -ho 'tests="[0-9]*"' "$SKT_XML" | grep -o '[0-9]*' | head -1)
        SKT_FAILED=$(grep -ho 'failures="[0-9]*"' "$SKT_XML" | grep -o '[0-9]*' | head -1)
    fi
    if [ "$SKT_RAN" -eq "$SENS_VECTORS" ] && [ "${SKT_FAILED:-1}" -eq 0 ]; then
        printf '  kotlin sensitivity: PASS  (%s/%s vectors)\n' "$SKT_RAN" "$SENS_VECTORS"
    else
        printf '  kotlin sensitivity: FAIL  (%s/%s ran)\n' "$SKT_RAN" "$SENS_VECTORS"
        SENSITIVITY_GREEN=false
    fi
else
    printf '\n  sensitivity:      none found in conformance/sensitivity\n'
    SENSITIVITY_GREEN=false
fi

# --- document shape --------------------------------------------------------
# Form IR §10.1, on both engines. This is the set conformance/vectors cannot
# express: every vector there assumes a form that compiled, so "this document
# must be refused" had nowhere to live and the divergence went unseen — Kotlin
# refusing nine document shapes at parse while Python crashed on them.
# Both engines must agree on the reason and the location, not just the outcome.

DOC_VECTORS=$(find conformance/malformed -name 'malformed-*.json' 2>/dev/null | wc -l | tr -d ' ')
DOCUMENT_GREEN=true

if [ "$DOC_VECTORS" -gt 0 ]; then
    printf '\n  document shape:   %s vectors\n' "$DOC_VECTORS"

    DPY_OUT=$(cd backend && "$PY" -m pytest tests/test_malformed_conformance.py -q 2>&1)
    if [ $? -eq 0 ]; then
        printf '  python documents: PASS\n'
    else
        printf '  python documents: FAIL\n'
        printf '%s\n' "$DPY_OUT" | tail -4 | sed 's/^/    | /'
        DOCUMENT_GREEN=false
    fi

    DKT_XML=shared/form-engine/build/test-results/jvmTest/TEST-com.dcp.form.MalformedConformanceTest.xml
    DKT_RAN=0
    if [ -f "$DKT_XML" ]; then
        # Two assertions per vector: the reason and location, and that the
        # refusal is still a CompileException to every caller.
        DKT_RAN=$(grep -ho 'tests="[0-9]*"' "$DKT_XML" | grep -o '[0-9]*' | head -1)
        DKT_FAILED=$(grep -ho 'failures="[0-9]*"' "$DKT_XML" | grep -o '[0-9]*' | head -1)
    fi
    if [ "$DKT_RAN" -eq $((DOC_VECTORS * 2)) ] && [ "${DKT_FAILED:-1}" -eq 0 ]; then
        printf '  kotlin documents: PASS  (%s/%s vectors)\n' "$((DKT_RAN / 2))" "$DOC_VECTORS"
    else
        printf '  kotlin documents: FAIL  (%s of %s assertions ran)\n' "$DKT_RAN" "$((DOC_VECTORS * 2))"
        DOCUMENT_GREEN=false
    fi
else
    printf '\n  document shape:   none found in conformance/malformed\n'
    DOCUMENT_GREEN=false
fi

CONFORMANCE_GREEN=false
[ "$PY_STATUS" -eq 0 ] && [ "$KT_STATUS" -eq 0 ] && \
    [ "$PY_RAN" -eq "$VECTORS" ] && [ "$KT_RAN" -eq "$VECTORS" ] && CONFORMANCE_GREEN=true

# ---------------------------------------------------------------------------
hr "2. Phase 0 deliverables"

# Form IR spec: spec file present and both engines green on every vector.
if [ -f specs/form-ir-v0.1.md ] && [ "$CONFORMANCE_GREEN" = true ] && [ "$DOCUMENT_GREEN" = true ]; then
    item "Form IR spec" "DONE" \
        "specs/form-ir-v0.1.md, both engines pass $VECTORS/$VECTORS + $DOC_VECTORS document"
elif [ -f specs/form-ir-v0.1.md ]; then
    item "Form IR spec" "PARTIAL" "spec exists but conformance is not green"
else
    item "Form IR spec" "NOT STARTED" "specs/form-ir-v0.1.md missing"
fi

# Sync protocol: spec file and/or a populated backend sync module.
SYNC_SPEC=$(find specs -name 'sync-protocol*' 2>/dev/null | head -1)
SYNC_CODE=$(find backend/app/modules/sync -name '*.py' ! -name '__init__.py' 2>/dev/null | wc -l | tr -d ' ')
if [ -n "$SYNC_SPEC" ] && [ "$SYNC_CODE" -gt 0 ]; then
    item "Sync protocol" "DONE" "$SYNC_SPEC + $SYNC_CODE module files"
elif [ -n "$SYNC_SPEC" ] || [ "$SYNC_CODE" -gt 0 ]; then
    item "Sync protocol" "PARTIAL" "spec: ${SYNC_SPEC:-none}, module files: $SYNC_CODE"
else
    item "Sync protocol" "NOT STARTED" "no spec, empty module"
fi

# ERD / DB schema: real migrations on disk.
MIGRATIONS=$(find backend/migrations/versions -name '*.py' ! -name '__init__.py' 2>/dev/null | wc -l | tr -d ' ')
ERD_SPEC=$(find specs -name '*erd*' 2>/dev/null | head -1)
if [ "$MIGRATIONS" -gt 0 ]; then
    item "ERD / DB schema" "DONE" "$MIGRATIONS migration(s) in backend/migrations/versions/"
elif [ -n "$ERD_SPEC" ]; then
    item "ERD / DB schema" "PARTIAL" "$ERD_SPEC exists, no migrations"
else
    item "ERD / DB schema" "NOT STARTED" "no migrations, no ERD spec"
fi

# OpenAPI contract. The file existing is not the deliverable — the file being
# what the app generates is, and a committed snapshot that has fallen behind the
# server is worse than none. So this runs the same --check CI runs rather than
# asking `find` whether a file is there.
ROUTES=$(grep -rE '@router\.(get|post|put|patch|delete)' backend/app/api 2>/dev/null | wc -l | tr -d ' ')
OPENAPI_SPEC=$(find specs -name '*openapi*' 2>/dev/null | head -1)
if [ -n "$OPENAPI_SPEC" ] && [ "$ROUTES" -gt 0 ]; then
    if "$PY" scripts/generate_api_contract.py --check >/dev/null 2>&1; then
        item "OpenAPI contract" "DONE" "$OPENAPI_SPEC, in step with $ROUTES routes"
    else
        item "OpenAPI contract" "STALE" "$OPENAPI_SPEC is not what the app generates"
        printf '                           run: python scripts/generate_api_contract.py\n'
    fi
elif [ "$ROUTES" -gt 0 ] || [ -n "$OPENAPI_SPEC" ]; then
    item "OpenAPI contract" "PARTIAL" "spec: ${OPENAPI_SPEC:-none}, routes in backend/app/api: $ROUTES"
else
    item "OpenAPI contract" "NOT STARTED" "no contract file, no routes"
fi

# Encryption envelope: a spec and/or crypto code anywhere in shared/ or backend/app.
ENC_SPEC=$(find specs \( -name '*encrypt*' -o -name '*envelope*' \) 2>/dev/null | head -1)
# Look for the implementation, not a test that merely mentions encryption.
ENC_CODE=$(find shared/core/src/commonMain backend/app/modules/crypto -type f \
    \( -name '*.py' -o -name '*.kt' \) -not -path '*/build/*' \
    -not -path '*/__pycache__/*' -not -name '__init__.py' 2>/dev/null | head -1)
if [ -n "$ENC_SPEC" ] && [ -n "$ENC_CODE" ] && [ "$CRYPTO_GREEN" = true ] && \
   [ "$SENSITIVITY_GREEN" = true ]; then
    item "Encryption envelope" "DONE" \
        "$ENC_SPEC, both engines pass $CRYPTO_VECTORS crypto + $SENS_VECTORS sensitivity vectors"
elif [ -n "$ENC_SPEC" ] && [ -n "$ENC_CODE" ] && [ "$CRYPTO_GREEN" = true ]; then
    item "Encryption envelope" "PARTIAL" \
        "crypto vectors green, but sensitivity propagation does not agree across engines"
elif [ -n "$ENC_SPEC" ] && [ -n "$ENC_CODE" ]; then
    item "Encryption envelope" "PARTIAL" "spec + code, but crypto vectors are not green on both engines"
elif [ -n "$ENC_SPEC" ] || [ -n "$ENC_CODE" ]; then
    item "Encryption envelope" "PARTIAL" "spec: ${ENC_SPEC:-none}, code: ${ENC_CODE:-none}"
else
    item "Encryption envelope" "NOT STARTED" "no spec, no crypto code"
fi

item "iOS Compose spike" "MANUAL" "cannot be auto-checked — inspect clients/iosApp by hand"

# ---------------------------------------------------------------------------
hr "3. Empty modules"

EMPTY_FOUND=false
for d in backend/app/modules/*/; do
    [ -d "$d" ] || continue
    case "$d" in */__pycache__/) continue ;; esac
    n=$(find "$d" -type f ! -name '__init__.py' ! -name '.gitkeep' ! -name '.DS_Store' \
        -not -path '*/__pycache__/*' 2>/dev/null | wc -l | tr -d ' ')
    if [ "$n" -eq 0 ]; then
        printf '  %s\n' "$d"
        EMPTY_FOUND=true
    fi
done
for d in shared/*/; do
    [ -d "$d" ] || continue
    n=$(find "$d" -type f \( -name '*.kt' -o -name '*.swift' \) ! -name 'Placeholder.kt' \
        -not -path '*/build/*' 2>/dev/null | wc -l | tr -d ' ')
    if [ "$n" -eq 0 ]; then
        printf '  %s (placeholder only)\n' "$d"
        EMPTY_FOUND=true
    fi
done
[ "$EMPTY_FOUND" = true ] || printf '  none\n'

# ---------------------------------------------------------------------------
hr "4. TODO / FIXME / NotImplementedError"

MARKERS=$(find shared backend/app -type f \( -name '*.py' -o -name '*.kt' \) \
    -not -path '*/build/*' -not -path '*/__pycache__/*' 2>/dev/null \
    | xargs grep -n -E 'TODO|FIXME|NotImplementedError' 2>/dev/null)
if [ -n "$MARKERS" ]; then
    printf '%s\n' "$MARKERS" | sed 's/^/  /'
else
    printf '  none\n'
fi

exit 0
