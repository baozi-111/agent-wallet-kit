# Ops lessons (2026-11-01 — 2026-11-05)

Notes from a week of Agentic Wallet minting and Pearl-style PoW. Public contracts and profile names below were already on the operational record. Machine paths, keys, and live proofs are not.

## Multi-profile BAW

Switch profiles with `OX_WALLET=<name>` or `ox-wallet switch <name>` before any preview or broadcast. Setting only `BINANCE_BAW_DIR` can leave the CLI on a different profile, so a tx goes out from the wrong address. Confirm `wallet address` on the target chain before spending.

One handle is not a global default. Scripts in this repo take the profile and the address from the environment.

## Free versus paid Agent-ID

Free Agent-ID mints that week ran on the `xiaogu.ai` profile. Paid mints were handed to a Feishu routine, and that routine may be paused. Do not assume the free profile and the paid path are the same process. The Ethereum template in `agentideth/` takes `OX_WALLET`, `FROM`, and `SHARES` so another profile is an env change.

## AGC A-tier

The A-tier path is `mintFree`, then `claimFree` after 24 hours. The daily 08:00 Asia/Shanghai job is a reminder only. It should not send a transaction by itself.

## HashDoge

HashDoge is a PoW NFT. Trading was expected only after about 1016 mints. A successful early mint is inventory, not liquid profit. Quote a real pool before treating it as a sell.

## Speed when the CA is already known

If the site already shows the contract and the price, quote mint cost and the DEX or BAW sell in parallel (`bsc-mint/scripts/fast_arb.py`) before a long source read. Write the experience entry after the attempt, including failures and timings. Reuse a family match only for the method shape. Re-read address, price, and arguments on the new contract.

## Pearl window

The 3 Nov window closed in about a minute: pre-mined proofs hit the daily cap as soon as `isLive` flipped. A single ~1 GH/s GPU that starts after refresh does not catch that. What mattered:

- GPU and submitter already up before the daily refresh (`startsAt + n * 86400`, not local midnight).
- Dual buffer: the card keeps mining while the previous batch is submitted.
- After `BROADCASTED`, start the next batch. Do not wait for the receipt on the hot path.
- No transfers or sells until the window is over. They share the wallet channel with `mineBatch`.
- Drop stale seed or target and recompute. Stop cleanly when `dailyRemaining` cannot cover the next batch.

Details and the checklist are in `pearl/docs/`.

## What stayed out of git

Private keys, seed phrases, session tokens, webhook URLs, QR logins, `.baw` profile directories, and live challenge or proof dumps. Challenge JSON produced by `pearl/challenge.py` is gitignored on purpose.

## 中文

- 切档案用 `OX_WALLET` 或 `ox-wallet switch`。只改 `BINANCE_BAW_DIR` 可能仍打到别的钱包。
- 免费 Agent-ID 走当时的 `xiaogu.ai`；付费走飞书，流程可能已暂停。不要把一个 handle 写死。
- AGC A 档：先 `mintFree`，24 小时后再 `claimFree`。每天 08:00（北京时间）只提醒，不发交易。
- HashDoge 是 PoW NFT，大约 1016 次 mint 之后才有交易。早期没有流动性，不要当成已经能卖出的利润。
- 网页上已有 CA 和价格时，先并行报铸造成本和卖出价，再做深研。
- 珍珠币窗口很短：开盘前预热，边挖边交，`BROADCASTED` 后不等回执，窗口内不转币。
