# Pearl PoW dual-buffer

GPU process finds nonces. A second process validates them and, only with `--execute`, previews and broadcasts `mineBatch`. Neither path transfers tokens.

Identity is not built in.

| Env | Role |
|---|---|
| `PEARL_WALLET` | address passed to `challenge(address,uint256)` |
| `PEARL_AGENT_ID` | agent id word |
| `OX_WALLET` | BAW profile name. Required even for a dry run of the submitter |
| `PEARL_TOKEN` | optional, defaults to the public Pearl token |
| `PEARL_INBOX` | directory of solution JSON files |

`BINANCE_BAW_DIR` is not set by these scripts. If you set it yourself, still set `OX_WALLET`, or the CLI can stay on another profile.

## A. Refresh the challenge (read-only)

```bash
export PEARL_WALLET=0xYourAddress
export PEARL_AGENT_ID=0xYourAgentId
python3 challenge.py -o /tmp/pearl-challenge.json
```

Copy that JSON to the Windows GPU folder. Do not commit it. The contract day rolls every 86400 seconds from `startsAt`, not at Beijing midnight. Use `nextRefreshAsiaShanghai` from the script.

## B. GPU (Windows, no signing)

```bat
cd C:\pearl_mine\gpu
mine_forever.bat
```

Each full batch of 16 lands in `outbox\pearl-batch-*.json`. Mining continues immediately. See `gpu/README.md`.

## C. Hand-off

Copy each new outbox file into `PEARL_INBOX` (default `./pearl-state/inbox`) as soon as it appears. Do not wait for a receipt.

## D. Submit

Dry run (default, no broadcast):

```bash
export OX_WALLET=your-profile
python3 submit_ff.py --once --skip-preview
```

Preview, still no broadcast:

```bash
python3 submit_ff.py --once
```

Broadcast, fire-and-forget, no receipt wait:

```bash
python3 submit_ff.py --execute
```

`inbox_submit_once.sh` is the same one-shot. Extra arguments are passed through, including `--execute` if you add it.

Behavior with `--execute`:

- Reject a solution whose `wallet` or `agent_id` does not match the env.
- Drop stale seed or target.
- Stop when `dailyRemaining` is below the batch estimate.
- `preview`, then `execute`. On `BROADCASTED`, move the file to `pearl-state/done` and take the next file.
- No `wallet send`, transfer, or swap.

## E. No transfers during the window

Move or sell tokens after mining stops. The submitter has no transfer path.

## Docs

- `docs/珍珠币挖矿优化清单.md` — checklist (also copied as `docs/pearl-mining-optimization.md`)
- `docs/retro-20261103.md` — 3 Nov window, zero credited proofs, and why

## Logs

On a real broadcast the sidecar `*.submit.json` has `preview_ms`, `execute_ms`, `batch_wall_ms`, `txHash`, `status`, `claims_at_submit`, and `dailyRemaining_at_submit`. GPU JSON has `mhs`, `elapsed`, `nonces`, `seed`, and `target`. Those files are gitignored.
