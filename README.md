# agent-wallet-kit

Reusable tooling for Binance Agentic Wallet (BAW) workflows: BSC mint precheck, a hot-path cost-versus-sell quote, Pearl-style PoW batch mining, and an AgentID Ethereum paid-mint template.

Scripts and notes only. This tree has no private keys, seed phrases, session tokens, webhook URLs, or live challenge dumps.

## Layout

| Path | What |
|---|---|
| `bsc-mint/` | Read-only precheck, `fast_arb` hot path, experience schema and index |
| `pearl/` | GPU miner plus dual-buffer submit. Broadcast is off unless `--execute` |
| `agentideth/` | Env-based `mint(shares,…)` template (`OX_WALLET`, `FROM`, `SHARES`) |
| `docs/lessons.md` | Ops notes from 2026-11-01 through 2026-11-05 |
| `skills/bsc-mint.md` | Short checklist for the BSC hot path |

`pearl/docs/珍珠币挖矿优化清单.md` and `pearl/docs/pearl-mining-optimization.md` are the same Chinese checklist (the export stored one document under both names). `pearl/docs/retro-20261103.md` is the 3 Nov window retro.

## Quick start

```bash
python3 -m pip install -r requirements.txt

# BSC precheck. No wallet, no signature.
python3 bsc-mint/scripts/precheck.py --ca 0xCBde1219862E61e3B2e9f417016f2C04f2E033Cf

# Cost versus sell quote. Does not sign.
export MINT_WALLET=0xYourAddress
python3 bsc-mint/scripts/fast_arb.py \
  --mint 0xMintCA --token 0xTokenCA --shares 10 --tokens-per-share 100000000 \
  --wallet "$MINT_WALLET"

# Pearl challenge snapshot (read-only RPC). Output is gitignored.
export PEARL_WALLET=0xYourAddress
export PEARL_AGENT_ID=0xYourAgentId
python3 pearl/challenge.py -o /tmp/pearl-challenge.json

# AgentID ETH: voucher + calldata + preview. Stops before broadcast.
export OX_WALLET=your-profile
export FROM=0xYourAddress
export SHARES=15
bash agentideth/mint_paid.sh
```

Foundry `cast` is required for the AgentID template. The Pearl GPU miner needs the NVIDIA CUDA toolkit on Windows. `baw` / `ox-baw` is required only when you preview or broadcast.

## Safety

- **Default is no sign.** `precheck.py`, `fast_arb.py`, and `sim_mint.py` never broadcast. `pearl/submit_ff.py` validates (and can preview) and broadcasts only with `--execute`. `agentideth/mint_paid.sh` stops after preview unless `AGENTID_EXECUTE=1`.
- **No keys in git.** Pass the profile and addresses through the environment. See `.env.example`.
- **Profile selection.** Set `OX_WALLET` (or run `ox-wallet switch <name>`). Do not rely on `BINANCE_BAW_DIR` alone; that variable can still point at a different profile.
- Do not commit `.env`, `.baw/`, challenge JSON, or proof batches. `.gitignore` covers those.

## 中文

可复用的 Binance Agentic Wallet 工具：BSC 铸造预检和热路径报价、珍珠币类 PoW 双缓冲挖交、AgentID 以太坊付费 mint 模板。默认不签名、不广播，仓库里没有私钥。多档案用 `OX_WALLET`，不要只依赖 `BINANCE_BAW_DIR`。本周操作教训在 `docs/lessons.md`。
