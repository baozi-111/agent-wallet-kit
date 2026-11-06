> Published note: the session below is historical (profile names, on-chain addresses, and timings). Machine-local `.baw` paths, keys, and live challenge dumps are not part of this repo. Current scripts read `OX_WALLET`, `PEARL_WALLET`, and `PEARL_AGENT_ID` from the environment and do not broadcast unless you pass `--execute`.

# 珍珠币类挖矿优化清单（最新合并稿）

> 基于 2026-11-02 xiaogu.ai 实盘：约 **18,791 枚 / 193 次提交**，窗口约 **19:55–20:17（Asia/Shanghai）**。  
> 对手同窗口量级约 **20 万枚**（5090 服务器）。  
> 2026-11-02 晚补充：对照本地文件时间戳 + 链上/BAW 流水，拆清「提交链路」各段耗时。  
> 用途：下次同类「PoW + mineBatch + 日额度」项目开盘前对照执行。

---

## 1. 结论（先看这几句）

1. **后期「等人确认」不是主因**；自动提交打开后，批间隔多在 20–70 秒。
2. **主因 = 开局未满速 + GPU 与提交串行空转 + 本机 5060 算力远低于 5090 多卡。**
3. **提交链路本身没大面积卡住**：纯 BAW 提交通常只要约 **3–30 秒**；拖节奏的是「等回执才继续挖」+「挖交不同时」+「挖矿中途转币抢通道」。
4. 要追 10× 量级，必须同时做：**开盘预热、fire-and-forget 边挖边交、多 Agent/多卡、收工再转出**；只改确认流程不够。

---

## 2. 本次数据快照

| 项 | 数值 |
|---|---|
| 钱包 | xiaogu.ai（`0x932a…7cA7`） |
| 产出 | ≈ 18,791.35 珍珠币 |
| 有效提交 | 193 次（1 次单挖 + 12×16 批） |
| 首笔 | 19:55:44 |
| 第一批 16 | 20:07:28（距首笔约 **12 分钟**） |
| 末笔 | 20:17:25 |
| 稳态（20:07–20:17） | 约 **50 秒/批**；其中 GPU 算 16 个约 **13–20 秒** |
| 本机算力 | RTX 5060 ≈ **1 GH/s**（30 bits 下约 1 秒/解，16 解 ≈ 17 秒） |
| 日额度 | 全网 `DAILY_MINING_CAP` ≈ 2000 万枚/日（合约无单钱包上限） |
| 单笔上限 | `MAX_BATCH = 16` |
| 中途转出 | **7 笔** 珍珠转至 `0x9d45b1f5…d38a`，与 mineBatch 穿插 |

**串行浪费估算（稳态）**  
每批墙钟 ~50s，计算仅 ~17s → 约 **2/3 时间 GPU 在等提交/回执**。

---

## 3. 慢在哪里（对照「确认 vs 算力 vs 提交」）

### 3.1 开局（损失最大）

- 先走 CPU（~0.1 MH/s）摸底，再搞 GPU 编译 / MSVC / `vcvars`。
- 首批仍走「预览 → 等人确认」。
- **约 12 分钟**窗口里对手已在满速交单；日额度竞争项目里，开盘前几十分钟权重极高。

### 3.2 稳态流水线（确认已放开后仍慢）

当时实际流程：

`挖满 16 → 停 GPU → 打包 calldata → BAW preview → execute → 等回执 → 再开挖`

问题：**算和交不同时**；BAW 往返 + 等链上确认时，显卡闲着。另有手工拷贝解到提交侧，没有本地闭环。

### 3.3 提交链路实测（不是「确认卡死」）

对照 `/tmp/pearl-batch*` 时间戳与 `xiaogu` 交易史：

| 阶段 | 多数耗时 | 说明 |
|---|---|---|
| BAW `preview`（模拟+风控） | **1–2 秒**（偶发 ~8 秒） | 首批偏慢 |
| BAW `execute`（托管签名并广播） | **1–15 秒** | 返回 `BROADCASTED` 即已发出 |
| 等回执（BSC 出块） | **约几秒** | 我们当时会等确认才开下一批 |
| **纯提交合计** | **约 3–30 秒** | 不是主瓶颈的「卡死」感来源 |

批与批之间偶发拉到 **1–2 分钟**，多半是：等下一批评解、等回执、或穿插转账——**不是确认弹窗**。

**挖矿窗口内穿插转出（加重空窗）**

- 共 **7 笔** ERC-20 转出：`xiaogu` → `0x9d45b1f5dcadf037e7142a5bfb4f4a5e4d19d38a`
- 与 `mineBatch` 抢同一条 BAW 通道，插入额外空窗
- **下次规则：挖矿窗口禁止转币；收工后再统一转出**

### 3.4 硬件档差

| 档位 | 粗算 30-bit | 16 解纯计算 |
|---|---|---|
| 5060 ≈ 1 GH/s | ~1.1 s/解 | ~17 s |
| 单卡 5090（更高） | 显著更快 | 数秒级 |
| 5090 多卡租用 | 常可达数倍～十几倍 | 亚秒～数秒/批 |

仅硬件就可能拉开数倍；再叠加对方无空窗、多号并行，可到约 **10×** 产量差。

### 3.5 合约侧（不是「单号封顶」）

已核实源码：**无单钱包挖矿上限**。限制主要是：

- 有效 `.ai` Agent ID  
- 全网每日额度  
- 每笔最多 16  
- proof 不可复用  
- 挖矿总供给约 9 亿枚  

`puzzleSeed = keccak(publicChallenge, wallet)`：钱包 seed 不随每笔 mine 变；target/reward 随全网 `successfulProofs` 变。入队前仍须用**当前** challenge 校验，过期则丢弃重算。

xiaogu 后期交不上，更像 **日额度耗尽 / 答案过期**，不是账号封顶。可换 `0xstudy` 等档案继续（仍受全网日额度约束）。

---

## 4. 下次开盘前 Checklist

### A. T-1 天～开盘前 1 小时（预热）

- [ ] GPU miner **提前编译好**，本机跑通一次 dry-run（读 challenge → 找 1 个 nonce → 校验 `proofDigest`）。
- [ ] 固定目录与命令（示例）：`C:\Users\admin\pearl_mine\gpu\` + `mine_forever.bat`。
- [ ] 钱包档案就绪：`ox-wallet list`，目标号 **CONNECTED**，Developer Mode 开。
- [ ] 预先拿到用户授权：**mineBatch 自动预览并提交，无需逐批确认**（写进当次任务指令）。
- [ ] 确认 RPC / 合约地址 / `WORK_BITS` 与官方执行数据一致，防用错旧包。
- [ ] （可选）5090 多卡机已开机、驱动/CUDA/同样二进制已部署。
- [ ] 明确 **挖矿窗口不转币**；收款地址收工后再用。

### B. 开盘瞬间（满速）

- [ ] 轮询 `isLive()` / `dailyRemaining()` / `challenge`，一亮立刻挖。
- [ ] **禁止**再走「先挖 1 个给人看」的慢路径。
- [ ] 多 Agent 时：**一号一进程**（不同 `BINANCE_BAW_DIR` / seed），并行提交。

### C. 稳态（边挖边交 + fire-and-forget）

- [ ] **双缓冲**：缓冲区 A 提交时，GPU 已在挖缓冲区 B。
- [ ] `execute` 返回 `BROADCASTED` 后 **立刻开下一批**，不等回执（后台可异步记 receipt）。
- [ ] 用户已授权则 **跳过人工确认**；preview 仅日志，成功则立刻 execute。
- [ ] **禁止**挖矿中途 `transfer` / 卖币；转出挪到收工。
- [ ] 提交失败（`RewardChanged` / stale nonce）：丢弃该批，用**最新** challenge 重挖，勿死磕旧解。
- [ ] `dailyRemaining < 下一批预估奖励` 时优雅停，避免整批 revert。

### D. 收尾

- [ ] 统一转出 / 卖出（若需要）。
- [ ] 汇总：claims、枚数、tx 列表、钱包余额、是否已转出。
- [ ] 记一笔复盘：本轮实际 MH/s、平均批周期、preview/execute/空窗秒数、是否穿插了非挖矿交易。

---

## 5. 目标架构（下次脚本应长这样）

```
┌─────────────┐     nonces[16]      ┌──────────────────────┐
│  GPU 常驻    │ ─────────────────► │ 提交队列              │
│  不停找解    │ ◄── 最新 challenge ─ │ preview → execute    │
└─────────────┘                     │ BROADCASTED 即返回    │
                                    │ （回执异步记日志）      │
                                    └──────────────────────┘
```

要点：

1. **GPU 进程与提交进程分离**（两进程或异步队列）。  
2. 每找到 16 个立刻入队；**不要等上一笔回执**再算/再交（fire-and-forget）。  
3. seed 相对钱包较稳定，但 target/reward 随全网进度变：入队前用**当前** challenge 校验，过期丢弃重算。  
4. 单钱包串行占 BAW；**多钱包才是真并行倍增**。  
5. 挖矿窗口 **BAW 只跑 mineBatch**，不穿插转账。  
6. 日志打：`MH/s`、本批耗时、排队等待、preview 耗时、execute 耗时、（异步）链上确认耗时。

---

## 6. 参数与命令备忘（珍珠币当次）

- 链：BSC `56`  
- Token：`0x7E2DA878217EB995F9e5d36eD32c9Cea52442681`  
- Registry：`0x60B9262456dE011F7d15a54CdD8c48bAaa8B022F`  
- `WORK_BITS=30`，`MAX_BATCH=16`，`DAILY_MINING_CAP≈2e7` 枚  
- 提交：`mineBatch(id, nonces, minTotalReward)`，`minTotal ≈ sum(reward)×99/100`  
- 档案切换：`ox-wallet switch <name>` 或 `OX_WALLET=<name>`  
- 站点：`https://xn--ai-bk6esc.net`  
- 本轮转出地址（仅收工用）：`0x9d45b1f5dcadf037e7142a5bfb4f4a5e4d19d38a`

---

## 7. 优先级排序（投入产出）

| 优先级 | 动作 | 预期收益 |
|---|---|---|
| P0 | 开盘预热 + 授权自动交 | 夺回开局十几分钟 |
| P0 | 边挖边交双缓冲 + **BROADCASTED 后不等回执** | 稳态吞吐接近纯计算上限（本机约从 50s/批打到 ~20s/批量级） |
| P0 | 挖矿窗口禁止转币 | 去掉与 mineBatch 抢 BAW 的空窗 |
| P0 | 开盘租 5090 多卡 | 数倍～十余倍算力 |
| P1 | 多 Agent 并行 | 近线性倍增（受日额度与 Gas 约束） |
| P2 | 内核/占用率微调 | 通常个位数～百分之几十，不如换卡/并行 |

---

## 8. 一句话备忘

**下次不要再「挖完一批再交、交完还等回执、中途还转币」；开盘前预热好，授权自动交，GPU 与广播并行，BROADCASTED 就开下一批，转出留到收工，有条件就上多卡+多号。**
