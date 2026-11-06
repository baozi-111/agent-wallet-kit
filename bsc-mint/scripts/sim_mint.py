#!/usr/bin/env python3
"""Build mint calldata and optionally ox-baw contract-call preview. NEVER execute."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib_rpc import encode_call, selector  # noqa: E402

LAST = ROOT / "out" / "last-precheck.json"
OUT = ROOT / "out" / "last-sim.json"


def build_calldata(signature: str, args: list) -> str:
    sig = signature.strip()
    if not sig.endswith(")"):
        # allow bare selector
        if sig.startswith("0x") and len(sig) == 10:
            return sig
        raise ValueError(f"bad signature: {signature}")
    types = sig[sig.find("(") + 1 : sig.rfind(")")]
    type_list = [t.strip() for t in types.split(",")] if types.strip() else []
    if len(type_list) != len(args):
        # default mint(uint256) qty=1
        if sig == "mint(uint256)" and not args:
            args = [1]
        elif not type_list and not args:
            pass
        else:
            raise ValueError(f"{sig} needs {len(type_list)} args, got {len(args)}")
    coerced = []
    for t, a in zip(type_list, args):
        if t == "address":
            coerced.append(a)
        elif t.startswith("uint") or t.startswith("int"):
            coerced.append(int(a, 0) if isinstance(a, str) else int(a))
        else:
            coerced.append(a)
    return encode_call(sig, *coerced)


def preview_baw(from_addr: str, to: str, value: str, input_data: str) -> dict:
    baw_dir = os.environ.get("BINANCE_BAW_DIR")
    if not baw_dir:
        return {
            "ran": False,
            "reason": "BINANCE_BAW_DIR not set — skip preview; calldata only",
            "cmd": (
                "ox-baw contract-call preview --binanceChainId 56 "
                f"--from {from_addr} --to {to} --value {value} --inputData {input_data} --json"
            ),
        }
    cmd = [
        "ox-baw",
        "contract-call",
        "preview",
        "--binanceChainId",
        "56",
        "--from",
        from_addr,
        "--to",
        to,
        "--value",
        str(value),
        "--inputData",
        input_data,
        "--json",
    ]
    # Never pass execute
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=os.environ.copy())
        ms = round((time.perf_counter() - t0) * 1000, 1)
        stdout = p.stdout.strip()
        try:
            parsed = json.loads(stdout) if stdout else None
        except json.JSONDecodeError:
            parsed = None
        return {
            "ran": True,
            "ms": ms,
            "returncode": p.returncode,
            "stdout": stdout[:8000],
            "stderr": (p.stderr or "")[:2000],
            "parsed": parsed,
            "cmd": " ".join(cmd),
            "execute": False,
        }
    except Exception as e:  # noqa: BLE001
        return {"ran": True, "error": str(e), "cmd": " ".join(cmd), "execute": False}


def main() -> int:
    ap = argparse.ArgumentParser(description="Simulate mint via calldata + optional baw preview (no execute)")
    ap.add_argument("--from-last", action="store_true", help="use out/last-precheck.json")
    ap.add_argument("--ca")
    ap.add_argument("--method", help="e.g. claim() or mint(uint256)")
    ap.add_argument("--arg", action="append", default=[], help="method args, repeatable")
    ap.add_argument("--value", default="0", help="wei value; default 0")
    ap.add_argument("--wallet", default=os.environ.get("MINT_WALLET") or "")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    match = {}
    ca = args.ca
    method = args.method
    wallet = args.wallet.strip()
    value = args.value

    if args.from_last:
        if not LAST.exists():
            print(json.dumps({"ok": False, "error": "missing last-precheck.json"}), file=sys.stderr)
            return 2
        last = json.loads(LAST.read_text())
        ca = ca or last.get("ca")
        wallet = wallet or (last.get("wallet") or "")
        match = last.get("experience_match") or {}
        mm = match.get("mintMethod") or {}
        method = method or mm.get("signature")
        if not args.arg and mm.get("argsTemplate"):
            args.arg = [str(x) for x in mm["argsTemplate"]]
        baw = last.get("ox_baw_preview") or {}
        if baw.get("calldata") and not method:
            calldata = baw["calldata"]
            method = mm.get("signature") or "from_last_calldata"
            report = {
                "ok": True,
                "ca": ca,
                "method": method,
                "calldata": calldata,
                "value_wei": value,
                "wallet": wallet or None,
                "preview": preview_baw(wallet, ca, value, calldata) if wallet else {"ran": False, "reason": "no wallet"},
                "safety": {"execute": False, "sign": False, "broadcast": False},
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime()),
            }
            Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

    if not ca or not method:
        print(json.dumps({"ok": False, "error": "need --ca/--method or --from-last"}), file=sys.stderr)
        return 2

    calldata = build_calldata(method, args.arg)
    preview = {"ran": False, "reason": "no --wallet / MINT_WALLET"}
    if wallet:
        if value != "0" and not str(value).isdigit() and not str(value).startswith("0x"):
            preview = {"ran": False, "reason": f"refusing preview with unresolved value={value}"}
        else:
            preview = preview_baw(wallet, ca, value, calldata)

    report = {
        "ok": True,
        "ca": ca,
        "method": method,
        "selector": selector(method) if method.endswith(")") else method,
        "args": args.arg,
        "calldata": calldata,
        "value_wei": value,
        "wallet": wallet or None,
        "experience_project_id": match.get("project_id"),
        "preview": preview,
        "safety": {
            "execute": False,
            "sign": False,
            "broadcast": False,
            "approve": False,
            "note": "sim_mint never calls contract-call execute",
        },
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime()),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
