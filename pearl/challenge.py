#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only Pearl challenge snapshot. Writes JSON for the GPU miner. Does not sign."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from Crypto.Hash import keccak as _K
except ImportError as e:
    raise SystemExit("need pycryptodome: python3 -m pip install pycryptodome") from e

DEFAULT_TOKEN = "0x7E2DA878217EB995F9e5d36eD32c9Cea52442681"
CHAIN_ID = 56
RPC_DEFAULT = "https://bsc-dataseed.binance.org/"
DAY_SEC = 86400
SHANGHAI = timezone(timedelta(hours=8))


def keccak(b: bytes) -> bytes:
    h = _K.new(digest_bits=256)
    h.update(b)
    return h.digest()


def selector(sig: str) -> str:
    return "0x" + keccak(sig.encode()).hex()[:8]


def pad32(x: int) -> bytes:
    return x.to_bytes(32, "big")


def eth_call(rpc: str, token: str, data: str) -> str:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": token, "data": data}, "latest"],
    }
    req = urllib.request.Request(
        rpc,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        j = json.load(r)
    if "error" in j:
        raise RuntimeError(j["error"])
    return j["result"]


def call_uint(rpc: str, token: str, sig: str) -> int:
    raw = bytes.fromhex(eth_call(rpc, token, selector(sig))[2:])
    return int.from_bytes(raw, "big")


def call_challenge(rpc: str, token: str, wallet: str, agent_id: int) -> dict:
    data = (
        selector("challenge(address,uint256)")
        + pad32(int(wallet, 16)).hex()
        + pad32(agent_id).hex()
    )
    raw = bytes.fromhex(eth_call(rpc, token, data)[2:])
    if len(raw) < 192:
        raise RuntimeError(f"challenge return too short: {len(raw)} bytes")
    return {
        "seed": "0x" + raw[0:32].hex(),
        "target": str(int.from_bytes(raw[32:64], "big")),
        "reward": str(int.from_bytes(raw[64:96], "big")),
        "eligible": int.from_bytes(raw[96:128], "big") != 0,
        "live_from_challenge": int.from_bytes(raw[128:160], "big") != 0,
        "claims": int.from_bytes(raw[160:192], "big"),
    }


def fmt_shanghai(ts: int) -> str:
    return datetime.fromtimestamp(ts, SHANGHAI).strftime("%Y-%m-%d %H:%M:%S Asia/Shanghai")


def require_addr(name: str, value: str) -> str:
    v = (value or "").strip()
    if not v.startswith("0x") or len(v) < 42:
        raise SystemExit(f"REFUSED: set {name} to a 0x address (env or flag). No address is built in.")
    return v


def build_snapshot(rpc: str, token: str, wallet: str, agent_id: str, handle: str) -> dict:
    agent_id_int = int(agent_id, 16)
    chal = call_challenge(rpc, token, wallet, agent_id_int)
    starts_at = call_uint(rpc, token, "startsAt()")
    mining_day = call_uint(rpc, token, "miningDay()")
    daily_remaining = call_uint(rpc, token, "dailyRemaining()")
    current_reward = call_uint(rpc, token, "currentReward()")
    is_live = call_uint(rpc, token, "isLive()") != 0
    successful_proofs = call_uint(rpc, token, "successfulProofs()")
    minted_today = call_uint(rpc, token, "mintedInBudgetDay()")
    daily_cap = call_uint(rpc, token, "DAILY_MINING_CAP()")

    now = int(time.time())
    if starts_at == 0:
        next_refresh = None
        day_end = None
    else:
        day_end = starts_at + (mining_day + 1) * DAY_SEC
        next_refresh = day_end
        if now >= day_end:
            next_refresh = starts_at + ((now - starts_at) // DAY_SEC + 1) * DAY_SEC

    batch16_est = current_reward * 16
    return {
        "wallet": wallet,
        "handle": handle or None,
        "agent_id": agent_id,
        "token": token,
        "chainId": CHAIN_ID,
        "seed": chal["seed"],
        "target": chal["target"],
        "reward": str(current_reward),
        "claims": successful_proofs,
        "eligible": chal["eligible"],
        "isLive": is_live,
        "dailyRemaining": str(daily_remaining),
        "mintedInBudgetDay": str(minted_today),
        "DAILY_MINING_CAP": str(daily_cap),
        "startsAt": starts_at,
        "miningDay": mining_day,
        "dayEnd": day_end,
        "nextRefresh": next_refresh,
        "nextRefreshAsiaShanghai": fmt_shanghai(next_refresh) if next_refresh else None,
        "startsAtAsiaShanghai": fmt_shanghai(starts_at) if starts_at else None,
        "batch16RewardEst": str(batch16_est),
        "canMineBatch16": bool(is_live and daily_remaining >= batch16_est),
        "fetchedAt": now,
        "fetchedAtAsiaShanghai": fmt_shanghai(now),
        "rpc": rpc,
        "note": "Live challenge snapshot. Do not commit this file.",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch a Pearl challenge snapshot (read-only)")
    ap.add_argument("-o", "--out", default=str(Path.cwd() / "pearl-challenge.json"))
    ap.add_argument("--rpc", default=os.environ.get("PEARL_RPC", RPC_DEFAULT))
    ap.add_argument("--token", default=os.environ.get("PEARL_TOKEN", DEFAULT_TOKEN))
    ap.add_argument("--wallet", default=os.environ.get("PEARL_WALLET", ""))
    ap.add_argument("--agent-id", default=os.environ.get("PEARL_AGENT_ID", ""))
    ap.add_argument(
        "--handle",
        default=os.environ.get("PEARL_HANDLE") or os.environ.get("OX_WALLET") or "",
        help="label only; not used in the eth_call",
    )
    args = ap.parse_args()
    wallet = require_addr("PEARL_WALLET", args.wallet)
    agent_id = require_addr("PEARL_AGENT_ID", args.agent_id)
    token = require_addr("PEARL_TOKEN", args.token)

    snap = build_snapshot(args.rpc, token, wallet, agent_id, args.handle.strip())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lean = {
        "wallet": snap["wallet"],
        "handle": snap["handle"],
        "agent_id": snap["agent_id"],
        "seed": snap["seed"],
        "target": snap["target"],
        "reward": snap["reward"],
        "claims": snap["claims"],
        "token": snap["token"],
        "dailyRemaining": snap["dailyRemaining"],
        "isLive": snap["isLive"],
        "startsAt": snap["startsAt"],
        "miningDay": snap["miningDay"],
        "nextRefreshAsiaShanghai": snap["nextRefreshAsiaShanghai"],
    }
    lean_path = out.with_name("pearl-challenge-lean.json")
    lean_path.write_text(json.dumps(lean, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("=" * 60)
    print("pearl challenge · read-only")
    print(f"wallet     : {snap['wallet']}")
    print(f"handle     : {snap['handle']}")
    print(f"isLive     : {snap['isLive']}")
    print(f"reward     : {snap['reward']}")
    print(f"dailyRem   : {snap['dailyRemaining']}")
    print(f"claims     : {snap['claims']}")
    print(f"miningDay  : {snap['miningDay']}")
    print(f"startsAt   : {snap['startsAtAsiaShanghai']}")
    print(f"nextRefresh: {snap['nextRefreshAsiaShanghai']}")
    print(f"canBatch16 : {snap['canMineBatch16']}")
    print(f"seed       : {snap['seed'][:18]}…")
    print(f"wrote      : {out}")
    print(f"lean       : {lean_path}")
    print("Do not commit these JSON files.")
    print("=" * 60)
    if not snap["isLive"]:
        print(
            "NOTE: isLive=false (paused / dailyRemaining < reward / supply). "
            "Wait for nextRefresh before submitting.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
