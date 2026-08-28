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

KT_OUT=$(./gradlew :shared:form-engine:jvmTest --rerun-tasks 2>&1)
KT_STATUS=$?
KT_XML=shared/form-engine/build/test-results/jvmTest/TEST-com.dcp.form.ConformanceTest.xml
KT_RAN=0
KT_FAILED=0
if [ -f "$KT_XML" ]; then
    KT_RAN=$(grep -o 'tests="[0-9]*"' "$KT_XML" | head -1 | grep -o '[0-9]*')
    KT_FAILED=$(grep -o 'failures="[0-9]*"' "$KT_XML" | head -1 | grep -o '[0-9]*')
fi
if [ "$KT_STATUS" -eq 0 ] && [ -f "$KT_XML" ]; then
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

CONFORMANCE_GREEN=false
[ "$PY_STATUS" -eq 0 ] && [ "$KT_STATUS" -eq 0 ] && \
    [ "$PY_RAN" -eq "$VECTORS" ] && [ "$KT_RAN" -eq "$VECTORS" ] && CONFORMANCE_GREEN=true

# ---------------------------------------------------------------------------
hr "2. Phase 0 deliverables"

# Form IR spec: spec file present and both engines green on every vector.
if [ -f specs/form-ir-v0.1.md ] && [ "$CONFORMANCE_GREEN" = true ]; then
    item "Form IR spec" "DONE" "specs/form-ir-v0.1.md, both engines pass $VECTORS/$VECTORS"
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

# OpenAPI contract: a contract file in specs/ and route handlers in the app.
ROUTES=$(grep -rE '@router\.(get|post|put|patch|delete)' backend/app/api 2>/dev/null | wc -l | tr -d ' ')
OPENAPI_SPEC=$(find specs -name '*openapi*' 2>/dev/null | head -1)
if [ -n "$OPENAPI_SPEC" ] && [ "$ROUTES" -gt 0 ]; then
    item "OpenAPI contract" "DONE" "$OPENAPI_SPEC + $ROUTES routes"
elif [ "$ROUTES" -gt 0 ] || [ -n "$OPENAPI_SPEC" ]; then
    item "OpenAPI contract" "PARTIAL" "spec: ${OPENAPI_SPEC:-none}, routes in backend/app/api: $ROUTES"
else
    item "OpenAPI contract" "NOT STARTED" "no contract file, no routes"
fi

# Encryption envelope: a spec and/or crypto code anywhere in shared/ or backend/app.
ENC_SPEC=$(find specs \( -name '*encrypt*' -o -name '*envelope*' \) 2>/dev/null | head -1)
ENC_CODE=$(find shared backend/app -type f \( -name '*.py' -o -name '*.kt' \) \
    -not -path '*/build/*' -not -path '*/__pycache__/*' 2>/dev/null \
    | xargs grep -l -i 'encrypt' 2>/dev/null | head -1)
if [ -n "$ENC_SPEC" ] && [ -n "$ENC_CODE" ]; then
    item "Encryption envelope" "DONE" "$ENC_SPEC + code in $ENC_CODE"
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
