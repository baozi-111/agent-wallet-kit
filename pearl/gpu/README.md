# Pearl GPU miner (Windows)

Finds nonces on an NVIDIA GPU. Does not sign or broadcast.

## Setup

1. Put this folder somewhere such as `C:\pearl_mine\gpu\`.
2. Install the CUDA toolkit (`mine_forever.bat` defaults to `CUDA\v13.0`) and the Visual Studio Build Tools `nvcc` uses.
3. Copy a fresh `pearl-challenge.json` from `python3 challenge.py` into this folder or its parent. It must contain `seed` and `target`. `wallet` and `agent_id` are copied into the solution file so the submitter can check them.

## Run

```bat
mine_forever.bat
```

- Compiles `mine_pearl_gpu.cu` once if the exe is missing.
- Mines batches of 16 (`PEARL_FIND_COUNT`).
- Writes `outbox\pearl-batch-YYYYMMDD-HHMMSS.json`, `pearl-solutions-latest.json`, and `pearl-solutions.json`.
- Starts the next batch immediately.

Copy each new outbox file to the submit inbox (`PEARL_INBOX`) while the GPU keeps going. The submitter defaults to no-sign until `--execute`.

## Env

| Var | Default | Meaning |
|---|---|---|
| `PEARL_LIMIT_SEC` | 900 in `mine_forever.bat` | max seconds per batch attempt |
| `PEARL_FIND_COUNT` | 16 | nonces per batch (max 16) |
| `PEARL_OUTBOX` | `outbox` | stamped batch directory |
| `PEARL_START_NONCE` | time-based, then the bat bumps it | search cursor |
| `PEARL_SKIP_NONCE` | unset | skip one known-used nonce |
| `PEARL_CUDA_BLOCKS` | SMs × 8 | launch config |
| `PEARL_CUDA_THREADS` | 256 | launch config |

Refresh `pearl-challenge.json` when seed, target, or reward change. Do not transfer tokens on the mining machine during the window.
