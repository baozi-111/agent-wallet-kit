# BSC Mint Kit (read-only)

URL or contract address in, experience match plus parallel `eth_call` out. Optional `ox-baw contract-call preview` when a profile is already configured.

**Does not sign, approve, transfer, or broadcast.**

## Hot path

When the site already shows the mint CA and the price, run this before a long source dive:

```bash
python3 scripts/fast_arb.py \
  --mint 0xMintCA --token 0xTokenCA --shares 10 --tokens-per-share 100000000 \
  --wallet "${MINT_WALLET:?set an address}"
```

Stdout is JSON with `go`, `spread_bnb`, `mint_cost_bnb`, and `sell_bnb_est`. `go` is a quote result. This process does not mint or sell.

## Precheck

```bash
python3 scripts/precheck.py --ca 0xCBde1219862E61e3B2e9f417016f2C04f2E033Cf
python3 scripts/precheck.py --url https://egg-nft.deed.page/
# calldata, and a preview only if MINT_WALLET is set and baw is logged in
python3 scripts/sim_mint.py --from-last
```

Output is stdout JSON plus `out/last-precheck.json` (gitignored). Useful fields: `ready_for_confirm`, `experience_match`, `risks`, `stage_timings_ms`, `ox_baw_preview_cmd`.

## Rules

- Allowed: `eth_call`, `eth_getCode`, storage reads, writing `out/last-precheck.json`, and `contract-call preview`.
- Not done here: `eth_sendRawTransaction`, approve, transfer, `contract-call execute`.
- A similar contract reuses the recognition method only. Re-read address, price, and arguments.
- Set `OX_WALLET` before any preview. Do not rely on `BINANCE_BAW_DIR` alone.

## Experience

`experience/SCHEMA.md` and `experience/index.json`. After a real attempt, append selectors, how price was read, failure reasons, and timings. Local evidence paths from the original machine were removed.

## Test

```bash
bash tests/test_precheck_smoke.sh
```

Needs network access to a public BSC RPC and `pycryptodome`.
