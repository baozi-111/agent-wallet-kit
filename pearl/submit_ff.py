#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pearl mineBatch submitter.

Default is no-sign: validate proofs and optionally preview, then stop.
Broadcast only with --execute (fire-and-forget after BROADCASTED; no receipt wait).

Never calls wallet send / transfer / market-order / swap.
Profile comes from OX_WALLET. Do not rely on BINANCE_BAW_DIR alone.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
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
MAX_BATCH = 16
SHANGHAI = timezone(timedelta(hours=8))
FORBIDDEN_BAW_SUBCMDS = {"send", "transfer", "market-order", "limit-order", "swap"}

WALLET = ""
AGENT_ID = ""
TOKEN = DEFAULT_TOKEN


def log(msg: str) -> None:
    ts = datetime.now(SHANGHAI).strftime("%H:%M:%S")
    print(f"[{ts} Asia/Shanghai] {msg}", flush=True)


def keccak(b: bytes) -> bytes:
    h = _K.new(digest_bits=256)
    h.update(b)
    return h.digest()


def selector(sig: str) -> str:
    return "0x" + keccak(sig.encode()).hex()[:8]


def pad32(x: int) -> bytes:
    return x.to_bytes(32, "big")


def eth_call(rpc: str, data: str) -> str:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": TOKEN, "data": data}, "latest"],
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


def call_uint(rpc: str, sig: str) -> int:
    return int.from_bytes(bytes.fromhex(eth_call(rpc, selector(sig))[2:]), "big")


def fetch_challenge(rpc: str) -> dict:
    data = (
        selector("challenge(address,uint256)")
        + pad32(int(WALLET, 16)).hex()
        + pad32(int(AGENT_ID, 16)).hex()
    )
    raw = bytes.fromhex(eth_call(rpc, data)[2:])
    return {
        "seed": raw[0:32],
        "seed_hex": "0x" + raw[0:32].hex(),
        "target": int.from_bytes(raw[32:64], "big"),
        "reward": int.from_bytes(raw[64:96], "big"),
        "eligible": int.from_bytes(raw[96:128], "big") != 0,
        "live": int.from_bytes(raw[128:160], "big") != 0,
        "claims": int.from_bytes(raw[160:192], "big"),
    }


def proof_ok(seed: bytes, nonce: int, target: int) -> bool:
    digest = int.from_bytes(keccak(seed + nonce.to_bytes(32, "big")), "big")
    return digest <= target


def baw_env() -> dict:
    env = dict(os.environ)
    ox = (env.get("OX_WALLET") or "").strip()
    if not ox:
        raise SystemExit(
            "REFUSED: set OX_WALLET to the BAW profile name. "
            "BINANCE_BAW_DIR alone can still point at the wrong profile."
        )
    env["OX_WALLET"] = ox
    return env


def parse_nonces(data: dict) -> list[int]:
    if "nonces" in data:
        raw = data["nonces"]
    elif "nonce" in data:
        raw = [data["nonce"]]
    else:
        raise ValueError("json missing nonces")
    nonces = [int(x) for x in raw]
    if not (1 <= len(nonces) <= MAX_BATCH):
        raise ValueError(f"nonce count {len(nonces)} not in 1..{MAX_BATCH}")
    return nonces


def build_mine_batch_calldata(nonces: list[int], min_total: int) -> str:
    agent = int(AGENT_ID, 16)
    body = pad32(agent) + pad32(96) + pad32(min_total) + pad32(len(nonces))
    for n in nonces:
        body += pad32(n)
    return "0x" + (
        bytes.fromhex(selector("mineBatch(uint256,uint256[],uint256)")[2:]) + body
    ).hex()


def run_baw(args: list[str]) -> tuple[int, str, str]:
    if any(a in FORBIDDEN_BAW_SUBCMDS for a in args):
        raise RuntimeError(f"REFUSED forbidden baw args: {args}")
    if "contract-call" not in args:
        raise RuntimeError(f"REFUSED: only baw contract-call allowed, got {args}")
    if "execute" in args and "--requestId" not in args:
        raise RuntimeError("REFUSED: execute requires --requestId from a preview")
    bin_name = os.environ.get("BAW_BIN", "baw")
    p = subprocess.run(
        [bin_name, *args],
        capture_output=True,
        text=True,
        env=baw_env(),
        timeout=120,
    )
    return p.returncode, p.stdout, p.stderr


def move_with_reason(src: Path, dest_dir: Path, reason: str | None = None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        dest = dest_dir / f"{src.stem}-{int(time.time())}{src.suffix}"
    shutil.move(str(src), str(dest))
    if reason:
        dest.with_suffix(dest.suffix + ".reason.txt").write_text(reason + "\n", encoding="utf-8")
    return dest


def write_report(path: Path, payload: dict) -> None:
    dest = path.with_suffix(path.suffix + ".dryrun.json")
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def estimate_min_total(reward: int, n: int, slip_bps: int) -> int:
    return reward * n * (10_000 - slip_bps) // 10_000


def check_identity(data: dict) -> str | None:
    wallet = data.get("wallet")
    if wallet and str(wallet).lower() != WALLET.lower():
        return f"solution wallet {wallet} != PEARL_WALLET {WALLET}"
    aid = data.get("agent_id")
    if aid and str(aid).lower() != AGENT_ID.lower():
        return f"agent_id mismatch: {aid}"
    return None


def process_one(
    path: Path,
    rpc: str,
    done_dir: Path,
    fail_dir: Path,
    slip_bps: int,
    require_live: bool,
    execute: bool,
    do_preview: bool,
) -> str:
    """Return 'broadcast' | 'dry-run' | 'fail' | 'stop'."""
    t_batch0 = time.time()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        if execute:
            move_with_reason(path, fail_dir, f"bad json: {e}")
        log(f"FAIL {path.name}: bad json")
        return "fail"

    mismatch = check_identity(data)
    if mismatch:
        if execute:
            move_with_reason(path, fail_dir, mismatch)
        log(f"FAIL {path.name}: {mismatch}")
        return "fail"

    try:
        nonces = parse_nonces(data)
    except Exception as e:
        if execute:
            move_with_reason(path, fail_dir, str(e))
        log(f"FAIL {path.name}: {e}")
        return "fail"

    try:
        is_live = call_uint(rpc, "isLive()") != 0
        daily_remaining = call_uint(rpc, "dailyRemaining()")
        chal = fetch_challenge(rpc)
    except Exception as e:
        if execute:
            move_with_reason(path, fail_dir, f"rpc error: {e}")
        log(f"FAIL {path.name}: rpc {e}")
        return "fail"

    reward = chal["reward"]
    batch_est = reward * len(nonces)
    if require_live and not is_live:
        reason = f"isLive=false dailyRemaining={daily_remaining} reward={reward}"
        if execute:
            move_with_reason(path, fail_dir, reason)
        log(f"STOP {path.name}: {reason}")
        return "stop"
    if daily_remaining < batch_est:
        reason = f"dailyRemaining {daily_remaining} < batchEst {batch_est}"
        if execute:
            move_with_reason(path, fail_dir, reason)
        log(f"STOP {path.name}: {reason}")
        return "stop"

    sol_seed = data.get("seed")
    sol_target = data.get("target")
    if sol_seed:
        s = str(sol_seed).lower()
        if not s.startswith("0x"):
            s = "0x" + s
        if s != chal["seed_hex"]:
            reason = "stale seed"
            if execute:
                move_with_reason(path, fail_dir, f"{reason} sol={s} chain={chal['seed_hex']}")
            log(f"FAIL {path.name}: {reason}")
            return "fail"
    if sol_target is not None and int(sol_target) != chal["target"]:
        if execute:
            move_with_reason(
                path,
                fail_dir,
                f"stale target sol={sol_target} chain={chal['target']}",
            )
        log(f"FAIL {path.name}: stale target")
        return "fail"

    bad = [n for n in nonces if not proof_ok(chal["seed"], n, chal["target"])]
    if bad:
        if execute:
            move_with_reason(path, fail_dir, f"invalid proofs for nonces: {bad[:3]}")
        log(f"FAIL {path.name}: {len(bad)} invalid proofs")
        return "fail"

    if "minTotalReward" in data:
        min_total = int(data["minTotalReward"])
    else:
        min_total = estimate_min_total(reward, len(nonces), slip_bps)

    calldata = build_mine_batch_calldata(nonces, min_total)
    log(
        f"{'EXECUTE' if execute else 'DRY-RUN'} {path.name} n={len(nonces)} "
        f"reward={reward} minTotal={min_total} rem={daily_remaining} claims={chal['claims']}"
    )

    preview = None
    preview_ms = None
    if do_preview or execute:
        t0 = time.time()
        try:
            rc, out, err = run_baw(
                [
                    "contract-call",
                    "preview",
                    "--binanceChainId",
                    str(CHAIN_ID),
                    "--from",
                    WALLET,
                    "--to",
                    TOKEN,
                    "--value",
                    "0",
                    "--inputData",
                    calldata,
                    "--json",
                ]
            )
        except FileNotFoundError:
            if execute:
                log(f"FAIL {path.name}: baw CLI not on PATH (BAW_BIN)")
                return "fail"
            log(f"preview skipped for {path.name}: baw CLI not on PATH")
            rc, out, err = None, "", ""
        preview_ms = int((time.time() - t0) * 1000) if rc is not None else None
        if rc is None:
            preview = None
        elif rc != 0:
            if execute:
                move_with_reason(path, fail_dir, f"preview rc={rc}\n{out}\n{err}")
            log(f"FAIL {path.name}: preview rc={rc} ({preview_ms}ms)")
            return "fail"
        else:
            try:
                preview = json.loads(out)
            except Exception as e:
                if execute:
                    move_with_reason(path, fail_dir, f"preview bad json: {e}\n{out}")
                log(f"FAIL {path.name}: preview json")
                return "fail"
            if not preview.get("success"):
                if execute:
                    move_with_reason(path, fail_dir, f"preview success=false\n{out}")
                log(f"FAIL {path.name}: preview rejected ({preview_ms}ms)")
                return "fail"
            log(f"preview ok {preview_ms}ms")

    if not execute:
        write_report(
            path,
            {
                "file": path.name,
                "mode": "dry-run",
                "sign": False,
                "broadcast": False,
                "nonces": len(nonces),
                "preview_ms": preview_ms,
                "preview_ran": preview is not None,
                "claims": chal["claims"],
                "dailyRemaining": daily_remaining,
                "batch_wall_ms": int((time.time() - t_batch0) * 1000),
                "note": "Pass --execute to broadcast. File left in the inbox.",
            },
        )
        log(f"NO-SIGN {path.name}: validated; not broadcast. Pass --execute to submit.")
        return "dry-run"

    rid = preview["data"]["requestId"]
    t1 = time.time()
    rc2, out2, err2 = run_baw(["contract-call", "execute", "--requestId", rid, "--json"])
    execute_ms = int((time.time() - t1) * 1000)
    if rc2 != 0:
        move_with_reason(path, fail_dir, f"execute rc={rc2}\n{out2}\n{err2}")
        log(f"FAIL {path.name}: execute rc={rc2} ({execute_ms}ms)")
        return "fail"
    try:
        exe = json.loads(out2)
    except Exception as e:
        move_with_reason(path, fail_dir, f"execute bad json: {e}\n{out2}")
        log(f"FAIL {path.name}: execute json")
        return "fail"

    status = (exe.get("data") or {}).get("status") or ""
    tx_hash = (exe.get("data") or {}).get("txHash")
    if not exe.get("success") or status.upper() != "BROADCASTED":
        move_with_reason(path, fail_dir, f"execute not BROADCASTED\n{out2}")
        log(f"FAIL {path.name}: status={status} ({execute_ms}ms)")
        return "fail"

    done_path = move_with_reason(path, done_dir)
    meta = {
        "file": done_path.name,
        "txHash": tx_hash,
        "status": status,
        "preview_ms": preview_ms,
        "execute_ms": execute_ms,
        "batch_wall_ms": int((time.time() - t_batch0) * 1000),
        "nonces": len(nonces),
        "reward": reward,
        "minTotal": min_total,
        "claims_at_submit": chal["claims"],
        "dailyRemaining_at_submit": daily_remaining,
        "broadcastedAtAsiaShanghai": datetime.now(SHANGHAI).isoformat(),
    }
    done_path.with_suffix(done_path.suffix + ".submit.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    log(
        f"BROADCASTED {done_path.name} tx={tx_hash} "
        f"preview={preview_ms}ms execute={execute_ms}ms "
        f"wall={meta['batch_wall_ms']}ms — next immediately (no receipt wait)"
    )
    return "broadcast"


def list_inbox(inbox: Path) -> list[Path]:
    skip_suffixes = (".submit.json", ".dryrun.json", ".reason.txt")
    return sorted(
        p
        for p in inbox.glob("*.json")
        if p.is_file() and not p.name.endswith(skip_suffixes)
    )


def require_addr(name: str, value: str) -> str:
    v = (value or "").strip()
    if not (v.startswith("0x") and len(v) >= 42):
        raise SystemExit(f"REFUSED: {name} must be a 0x address. Nothing is hard-coded.")
    return v


def main() -> None:
    global WALLET, AGENT_ID, TOKEN
    state = Path(os.environ.get("PEARL_STATE_DIR", str(Path.cwd() / "pearl-state")))
    ap = argparse.ArgumentParser(description="Pearl mineBatch submitter (no-sign unless --execute)")
    ap.add_argument("--inbox", default=os.environ.get("PEARL_INBOX", str(state / "inbox")))
    ap.add_argument("--done", default=os.environ.get("PEARL_DONE", str(state / "done")))
    ap.add_argument("--fail", default=os.environ.get("PEARL_FAIL", str(state / "fail")))
    ap.add_argument("--rpc", default=os.environ.get("PEARL_RPC", RPC_DEFAULT))
    ap.add_argument("--token", default=os.environ.get("PEARL_TOKEN", DEFAULT_TOKEN))
    ap.add_argument("--wallet", default=os.environ.get("PEARL_WALLET", ""))
    ap.add_argument("--agent-id", default=os.environ.get("PEARL_AGENT_ID", ""))
    ap.add_argument("--poll", type=float, default=1.0)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", action="store_true", help="loop; requires --execute")
    ap.add_argument("--slip-bps", type=int, default=100)
    ap.add_argument("--allow-not-live", action="store_true")
    ap.add_argument("--max-batches", type=int, default=0)
    ap.add_argument(
        "--execute",
        action="store_true",
        help="broadcast after preview. Default is validate/preview only.",
    )
    ap.add_argument(
        "--skip-preview",
        action="store_true",
        help="dry-run only: skip baw preview (ignored when --execute)",
    )
    args = ap.parse_args()

    if not (os.environ.get("OX_WALLET") or "").strip():
        raise SystemExit(
            "REFUSED: set OX_WALLET to the BAW profile. Do not rely on BINANCE_BAW_DIR alone."
        )
    WALLET = require_addr("PEARL_WALLET", args.wallet)
    AGENT_ID = require_addr("PEARL_AGENT_ID", args.agent_id)
    TOKEN = require_addr("PEARL_TOKEN", args.token)

    if args.watch and not args.execute:
        raise SystemExit("REFUSED: --watch broadcasts in a loop. Pass --execute as well. Default is no-sign.")
    if args.execute and not args.once and not args.watch:
        args.watch = True

    inbox = Path(args.inbox)
    done = Path(args.done)
    fail = Path(args.fail)
    inbox.mkdir(parents=True, exist_ok=True)
    if args.execute:
        done.mkdir(parents=True, exist_ok=True)
        fail.mkdir(parents=True, exist_ok=True)

    log(
        f"submit_ff start | mode={'execute' if args.execute else 'no-sign'} | "
        f"OX_WALLET={os.environ.get('OX_WALLET')} | inbox={inbox}"
    )
    if not args.execute:
        log("rules: default no-sign. --execute broadcasts and does not wait for a receipt.")
    else:
        log("rules: fire-and-forget after BROADCASTED; no receipt wait; no transfers")

    ok_count = 0
    while True:
        files = list_inbox(inbox)
        if files:
            log(f"queue depth={len(files)}")
        for path in files:
            if not path.exists():
                continue
            status = process_one(
                path,
                args.rpc,
                done,
                fail,
                args.slip_bps,
                require_live=not args.allow_not_live,
                execute=args.execute,
                do_preview=not args.skip_preview,
            )
            if status in ("broadcast", "dry-run"):
                ok_count += 1
                if args.max_batches and ok_count >= args.max_batches:
                    log(f"hit --max-batches={args.max_batches}, exit")
                    return
            elif status == "stop":
                log("stop (not live or daily remaining short)")
                return
        if not args.watch:
            log(f"pass done; ok={ok_count} execute={args.execute}")
            return
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
