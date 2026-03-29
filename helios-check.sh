#!/usr/bin/env bash
# helios-check.sh - Quick health check for Helios VPS deployment
#
# Usage:
#   ./helios-check.sh              # Run safe suite (skip live_db)
#   ./helios-check.sh --full       # Run full suite (all tests)
#   ./helios-check.sh --smoke      # Quick smoke test (imports + screen_name only)
#
# Install as alias:
#   echo 'alias helios-check="~/Desktop/Helios-Package\ Merged/helios-check.sh"' >> ~/.zshrc

set -euo pipefail

VPS="root@209.38.141.101"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/xiphos_do}"
CONTAINER="xiphos-xiphos-1"
SSH_OPTS="-i ${SSH_KEY} -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new"
MODE="${1:---safe}"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

header() { echo -e "\n${CYAN}=== $1 ===${NC}"; }
pass()   { echo -e "${GREEN}PASS${NC} $1"; }
fail()   { echo -e "${RED}FAIL${NC} $1"; }
warn()   { echo -e "${YELLOW}WARN${NC} $1"; }

run_remote() {
    ssh ${SSH_OPTS} ${VPS} "docker exec ${CONTAINER} $1"
}

# ── Pre-flight ──
header "Helios Health Check ($(date '+%Y-%m-%d %H:%M:%S %Z'))"
echo -e "  VPS:       ${VPS}"
echo -e "  Container: ${CONTAINER}"
echo -e "  Mode:      ${MODE}"

# ── SSH connectivity ──
header "Connectivity"
if ssh ${SSH_OPTS} ${VPS} "echo ok" > /dev/null 2>&1; then
    pass "SSH connection"
else
    fail "SSH connection - cannot reach ${VPS}"
    exit 1
fi

# ── Container running ──
if ssh ${SSH_OPTS} ${VPS} "docker ps --format '{{.Names}}' | grep -q ${CONTAINER}" 2>/dev/null; then
    pass "Container ${CONTAINER} running"
else
    fail "Container ${CONTAINER} not running"
    exit 1
fi

# ── Module imports ──
header "Module Imports"
for mod in ofac fgamlogit decision_engine regulatory_gates; do
    if run_remote "python3 -c \"import sys; sys.path.insert(0,'/app/backend'); import ${mod}; print('ok')\"" 2>/dev/null | grep -q ok; then
        pass "${mod}"
    else
        fail "${mod} import"
    fi
done

# ── Version check ──
header "Version Check"
VERSION=$(run_remote "python3 -c \"import sys; sys.path.insert(0,'/app/backend'); from fgamlogit import score_vendor; print('ok')\"" 2>/dev/null)
if echo "$VERSION" | grep -q ok; then
    pass "fgamlogit.score_vendor() callable"
else
    fail "fgamlogit.score_vendor() broken"
fi

# ── Smoke test: screen_name ──
header "Smoke Test: Sanctions Screening"
SCREEN_OUT=$(run_remote "python3 -c \"
import sys; sys.path.insert(0,'/app/backend')
from ofac import screen_name
r = screen_name('Huawei Technologies')
print(f'score={r.best_score:.3f} matched={r.matched_name}')
\"" 2>/dev/null)
if echo "$SCREEN_OUT" | grep -q "score="; then
    SCORE=$(echo "$SCREEN_OUT" | grep -o 'score=[0-9.]*' | cut -d= -f2)
    if (( $(echo "$SCORE >= 0.75" | bc -l) )); then
        pass "screen_name('Huawei Technologies') -> ${SCREEN_OUT}"
    else
        warn "screen_name('Huawei Technologies') score low: ${SCREEN_OUT}"
    fi
else
    fail "screen_name() returned unexpected output"
fi

# ── Smoke test: decision engine ──
DECISION_OUT=$(run_remote "python3 -c \"
import sys; sys.path.insert(0,'/app/backend')
from ofac import screen_name
from decision_engine import classify_alert
r = screen_name('Huawei Technologies')
d = classify_alert(r, vendor_country='CN')
print(f'category={d.category} weight={d.override_risk_weight}')
\"" 2>/dev/null)
if echo "$DECISION_OUT" | grep -q "category=DEFINITE"; then
    pass "classify_alert(Huawei) -> ${DECISION_OUT}"
else
    warn "classify_alert(Huawei) unexpected: ${DECISION_OUT}"
fi

if [ "$MODE" = "--smoke" ]; then
    header "SMOKE TEST COMPLETE"
    exit 0
fi

# ── Test suite ──
header "Test Suite"
if [ "$MODE" = "--full" ]; then
    echo "Running FULL suite (all tests, including live_db)..."
    PYTEST_CMD="python3 -m pytest /app/tests/ -o addopts= --tb=short -q"
else
    echo "Running SAFE suite (skipping live_db cases)..."
    PYTEST_CMD="python3 -m pytest /app/tests/ -m 'not live_db' -o addopts= --tb=short -q"
fi

TEST_OUTPUT=$(run_remote "${PYTEST_CMD}" 2>&1) || true
echo "$TEST_OUTPUT"

# ── Parse results ──
PASSED=$(echo "$TEST_OUTPUT" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo "0")
FAILED=$(echo "$TEST_OUTPUT" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo "0")
ERRORS=$(echo "$TEST_OUTPUT" | grep -oE '[0-9]+ error' | grep -oE '[0-9]+' || echo "0")
DESELECTED=$(echo "$TEST_OUTPUT" | grep -oE '[0-9]+ deselected' | grep -oE '[0-9]+' || echo "0")

header "RESULTS"
echo -e "  Passed:     ${GREEN}${PASSED}${NC}"
[ "$FAILED" != "0" ] && echo -e "  Failed:     ${RED}${FAILED}${NC}" || echo -e "  Failed:     ${FAILED}"
[ "$ERRORS" != "0" ] && echo -e "  Errors:     ${RED}${ERRORS}${NC}" || echo -e "  Errors:     ${ERRORS}"
[ "$DESELECTED" != "0" ] && echo -e "  Deselected: ${YELLOW}${DESELECTED}${NC}"

if [ "$FAILED" = "0" ] && [ "$ERRORS" = "0" ]; then
    echo -e "\n${GREEN}HEALTH CHECK PASSED${NC}"
    exit 0
else
    echo -e "\n${RED}HEALTH CHECK FAILED${NC}"
    exit 1
fi
