---
name: bsc-mint
description: Use when the user pastes a BSC mint URL or contract address, asks to precheck a mint, or wants a mint-then-sell quote. Run the hot path first. Do not sign until they explicitly authorize a separate execute step.
---

# BSC mint hot path

Kit root: `bsc-mint/` in this repo.

1. If the page already shows the CA, unit price, and share count, do not start with a full JS or Sourcify read. Quote cost and sell together:

```bash
python3 bsc-mint/scripts/fast_arb.py \
  --mint 0xMint --token 0xToken --shares 10 --tokens-per-share 100000000 \
  --wallet "$MINT_WALLET"
```

Read `go`, `spread_bnb`, `mint_cost_bnb`, `sell_bnb_est`. The script does not sign.

2. Before any preview, `ox-wallet switch <name>` or export `OX_WALLET`. Confirm the wallet address. `BINANCE_BAW_DIR` alone is not a profile switch.

3. Use `precheck.py` when there is no CA yet, the mechanism is unfamiliar, or the hot path cannot price the mint.

4. No `execute` and no value until the operator clearly authorizes that spend. A quote is not authorization.

5. After an attempt, update `bsc-mint/experience/index.json` with selectors, failure reasons, and timings. Re-verify price and addresses even when the bytecode family matches.

| Situation | Action |
|---|---|
| `go=true` and the operator authorized mint+sell | Preview, then execute outside this kit, then market-sell. Write the experience row after. |
| `spread` ≤ 0 | Report the numbers. |
| URL only | Extract the CA from the page, then run `fast_arb` or `precheck`. |
| Unknown method or a typed-data signature | Stop and research. Do not guess calldata. |
