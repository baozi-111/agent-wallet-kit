# Experience schema (BSC Mint Kit)

`index.json` 是历史经验库。新项目预检时优先按 bytecode 前缀 / selector 集合匹配；命中后只能复用识别方法，**地址、价格、交易参数必须重新链上核对**。

## Root

| Field | Type | Notes |
|---|---|---|
| schemaVersion | int | 当前为 1 |
| chainId | int | 固定 56 (BSC) |
| updatedAt | string | Asia/Shanghai ISO8601 |
| projects | array | 见下 |

## Project entry

| Field | Type | Notes |
|---|---|---|
| id | string | 稳定短 id，如 `egg-nft` |
| name | string | 展示名 |
| url | string\|null | 官网 / mint 页 |
| ca | string | 主 mint 合约 checksum/any-case OK，脚本会 lower |
| chainId | int | 56 |
| proxy | string\|null | 代理地址（若 CA 本身是代理则 ca=proxy） |
| implementation | string\|null | EIP-1967 实现；无代理则为 null |
| bytecodeSha256 | string\|null | runtime code sha256 |
| bytecodePrefix16 | string\|null | sha256 前 16 hex，快速匹配 |
| selectors | object | `{ "sig": "0x........", ... }` 常用入口 |
| mintMethod | object | `{ "signature", "selector", "valueMode": "zero\|wei\|quote", "argsTemplate": [...] }` |
| price | object | `{ "freePath": bool, "paidNote": string, "readFns": [sig...] }` |
| eligibility | object | Agent ID / WL / PoW 等说明 + `readFns` |
| statusReads | array | 如 `publicMintOpen()`, `paused()`, `info()` |
| successPath | string | 曾验证成功的路径摘要 |
| failureReasons | array | 已知失败原因 |
| timings | object | 历史预检/模拟耗时 ms（可选） |
| firstSeen | string | Asia/Shanghai |
| lastVerified | string | Asia/Shanghai |
| outcome | string | `success\|skipped_paid\|failed\|sold_out\|unknown` |
| confidence | number | 0–1，证据完整度 |
| source_files | array | 本地证据路径 |
| notes | string\|null | 自由备注 |
| matchHints | object | `{ "selectorSet": [...], "family": "deed-claim\|agent-launch\|sigil-quote\|gseed-qty" }` |

## Matching rules (precheck)

1. Exact CA hit → reuse method definitions, re-verify all reads.
2. Else `bytecodePrefix16` equal → same family candidate.
3. Else Jaccard(`selectorSet`) ≥ 0.5 → weak candidate; escalate AI if no status reads succeed.
4. Always re-read price / open / remaining on the **new** address.
