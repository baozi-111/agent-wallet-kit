#!/usr/bin/env bash
# AgentID ETH paid mint template.
# Builds a voucher + mint(shares,…) calldata. Default is no-sign.
# Broadcast only when AGENTID_EXECUTE=1.
#
# Required:
#   OX_WALLET   BAW profile name (ox-wallet). Do not rely on BINANCE_BAW_DIR alone.
#   FROM        Ethereum address that pays (0x…)
#   SHARES      share count, e.g. 15
# Optional:
#   AGENTID_HANDLE       defaults to OX_WALLET
#   AGENTID_MINT         mint contract (public default below)
#   ETH_RPC              Ethereum RPC
#   AGENTID_MINT_START   unix seconds; wait until then if set
#   AGENTID_API          voucher endpoint
#   AGENTID_OUT_DIR      where calldata/preview files go (gitignored)
#   AGENTID_EXECUTE=1    actually broadcast after a successful preview
#   BAW_BIN              baw CLI, default ox-baw
set -euo pipefail

: "${OX_WALLET:?set OX_WALLET to the BAW profile name}"
: "${FROM:?set FROM to the Ethereum address that pays}"
: "${SHARES:?set SHARES (integer share count)}"

case "$FROM" in
  0x*) ;;
  *) echo "ABORT: FROM must be a 0x address" >&2; exit 2 ;;
esac
case "$SHARES" in
  ''|*[!0-9]*) echo "ABORT: SHARES must be an integer" >&2; exit 2 ;;
esac

HANDLE="${AGENTID_HANDLE:-$OX_WALLET}"
MINT="${AGENTID_MINT:-0xB27e219a28dCDE18278355e41C5bdc8828eec459}"
RPC="${ETH_RPC:-https://ethereum-rpc.publicnode.com}"
API="${AGENTID_API:-https://agentideth.com/api/voucher}"
BAW_BIN="${BAW_BIN:-ox-baw}"
OUT_DIR="${AGENTID_OUT_DIR:-$(cd "$(dirname "$0")" && pwd)/out}"
mkdir -p "$OUT_DIR"

export OX_WALLET
export RPC

echo "==== $(date -Is) AgentID paid mint template ===="
echo "profile=$OX_WALLET handle=$HANDLE from=$FROM shares=$SHARES mint=$MINT"
echo "mode=$([[ "${AGENTID_EXECUTE:-}" == 1 ]] && echo execute || echo no-sign)"

if [[ -n "${AGENTID_MINT_START:-}" && "${AGENTID_MINT_START}" != 0 ]]; then
  now=$(date +%s)
  if (( now < AGENTID_MINT_START )); then
    echo "waiting until mint start $AGENTID_MINT_START"
    sleep $(( AGENTID_MINT_START - now + 1 ))
  fi
fi

if ! command -v cast >/dev/null 2>&1; then
  echo "ABORT: cast (foundry) is not on PATH" >&2
  exit 2
fi

bal=$(cast balance "$FROM" --rpc-url "$RPC")
echo "ETH bal wei=$bal"
if [[ "$bal" == "0" ]]; then
  echo "ABORT: no ETH on Ethereum for $FROM" >&2
  exit 2
fi

V=$(curl -sS -m 20 -X POST "$API" \
  -H 'content-type: application/json' \
  -d "{\"handle\":\"$HANDLE\",\"minter\":\"$FROM\",\"wl\":false,\"shares\":$SHARES,\"paid\":true}")
printf '%s\n' "$V" > "$OUT_DIR/last-voucher.json"

python3 - "$V" "$OUT_DIR" <<'PY'
import json, os, sys, subprocess
v = json.loads(sys.argv[1])
out_dir = sys.argv[2]
if not v.get("ok"):
    print("ABORT: voucher not ok", file=sys.stderr)
    sys.exit(4)
agent = int(v["agent_id"])
nonce = int(v["nonce"])
deadline = int(v["deadline"])
sig = v["signature"]
shares = int(v["shares"])
mint = v["mint"]
rpc = os.environ.get("RPC", "https://ethereum-rpc.publicnode.com")
q = int(subprocess.check_output(
    ["cast", "call", mint, "quoteEth(uint256)(uint256)", str(shares), "--rpc-url", rpc],
    text=True,
).split()[0])
max_cost = q * 108 // 100
min_out = 0
calldata = subprocess.check_output([
    "cast", "calldata",
    "mint(uint256,uint256,uint256,uint256,bytes,uint256,uint256)",
    str(shares), str(agent), str(nonce), str(deadline), sig, str(max_cost), str(min_out),
], text=True).strip()
open(os.path.join(out_dir, "last-calldata.txt"), "w").write(calldata)
open(os.path.join(out_dir, "last-value.txt"), "w").write(str(max_cost))
print(f"quote_wei={q} max_cost_wei={max_cost} deadline={deadline} mint={mint}")
print("voucher signature stored under out/ (gitignored); not printed")
PY

VALUE=$(cat "$OUT_DIR/last-value.txt")
DATA=$(cat "$OUT_DIR/last-calldata.txt")

if ! command -v "$BAW_BIN" >/dev/null 2>&1; then
  echo "baw CLI ($BAW_BIN) not on PATH; calldata is in $OUT_DIR"
  if [[ "${AGENTID_EXECUTE:-}" == 1 ]]; then
    echo "ABORT: cannot execute without $BAW_BIN" >&2
    exit 3
  fi
  echo "NO-SIGN: preview skipped. Set AGENTID_EXECUTE=1 only after you have reviewed calldata."
  exit 0
fi

PREV=$("$BAW_BIN" contract-call preview \
  --binanceChainId 1 \
  --from "$FROM" \
  --to "$MINT" \
  --value "$VALUE" \
  --inputData "$DATA" \
  --json)
printf '%s\n' "$PREV" > "$OUT_DIR/last-preview.json"
REQ=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print((d.get("data") or {}).get("requestId") or "")' "$OUT_DIR/last-preview.json")
echo "preview_request=${REQ:-<none>}"
if [[ -z "$REQ" ]]; then
  echo "ABORT: preview returned no requestId (see $OUT_DIR/last-preview.json)" >&2
  exit 3
fi

if [[ "${AGENTID_EXECUTE:-}" != 1 ]]; then
  echo "NO-SIGN: preview ok. Set AGENTID_EXECUTE=1 to broadcast this request."
  exit 0
fi

EXEC=$("$BAW_BIN" contract-call execute --requestId "$REQ" --json)
printf '%s\n' "$EXEC" > "$OUT_DIR/last-exec.json"
echo "execute written to $OUT_DIR/last-exec.json"
