#!/usr/bin/env bash
# Smoke: precheck against known experience CAs; assert JSON keys; exit 0.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
OUT_DIR="$ROOT/out/smoke"
mkdir -p "$OUT_DIR"

# Egg NFT + NIULAI from experience/index.json
CAS=(
  "0xCBde1219862E61e3B2e9f417016f2C04f2E033Cf"
  "0x15e47c22df42D94Fa2f0aD078Fec5Bea6453d5cF"
)

REQUIRED_KEYS=(
  ok chainId ca checked_at experience_match reads risks ready_for_confirm
  stage_timings_ms safety escalate_ai
)

fail=0
for ca in "${CAS[@]}"; do
  out="$OUT_DIR/precheck_${ca}.json"
  echo "[smoke] precheck $ca"
  if ! "$PY" scripts/precheck.py --ca "$ca" --out "$out" >"$OUT_DIR/stdout_${ca}.json"; then
    echo "[smoke] FAIL: precheck exit non-zero for $ca" >&2
    fail=1
    continue
  fi
  "$PY" - "$out" "${REQUIRED_KEYS[@]}" <<'PY'
import json, sys
path = sys.argv[1]
keys = sys.argv[2:]
data = json.load(open(path))
missing = [k for k in keys if k not in data]
if missing:
    print("missing keys:", missing)
    sys.exit(1)
if data.get("chainId") != 56:
    print("bad chainId", data.get("chainId")); sys.exit(1)
if not isinstance(data.get("stage_timings_ms"), dict):
    print("stage_timings_ms not dict"); sys.exit(1)
em = data.get("experience_match") or {}
if not em.get("mode"):
    print("experience_match.mode missing"); sys.exit(1)
safety = data.get("safety") or {}
if safety.get("broadcast") or safety.get("execute") or safety.get("sign"):
    print("safety flags must be false"); sys.exit(1)
print("ok", data["ca"], "match=", em.get("mode"), em.get("project_id"), "ready=", data.get("ready_for_confirm"), "total_ms=", data["stage_timings_ms"].get("total_ms"))
PY
done

# sim_mint dry (no BAW required)
echo "[smoke] sim_mint --from-last (calldata only)"
"$PY" scripts/precheck.py --ca "${CAS[0]}" --out "$ROOT/out/last-precheck.json" >/dev/null
"$PY" scripts/sim_mint.py --from-last --out "$OUT_DIR/sim.json" >/dev/null
"$PY" - "$OUT_DIR/sim.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d.get("ok") and d.get("calldata","").startswith("0x")
assert d.get("safety",{}).get("execute") is False
print("sim ok", d.get("method"), d.get("calldata")[:18])
PY

if [[ "$fail" -ne 0 ]]; then
  echo "[smoke] FAILED" >&2
  exit 1
fi
echo "[smoke] PASSED"
exit 0
