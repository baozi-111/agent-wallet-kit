#!/usr/bin/env python3
"""BSC mint precheck: experience match + parallel eth_call. Read-only; never sends txs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib_rpc import (  # noqa: E402
    COMMON_MINT_SIGS,
    COMMON_STATUS_SIGS,
    EIP1967_IMPL_SLOT,
    decode_bool,
    decode_uint,
    encode_call,
    get_code,
    impl_from_eip1967,
    parallel_calls,
    selector,
)

EXP_PATH = ROOT / "experience" / "index.json"
OUT_PATH = ROOT / "out" / "last-precheck.json"
CA_RE = re.compile(r"0x[a-fA-F0-9]{40}")


def now_shanghai_label() -> str:
    # box clock is Asia/Shanghai
    return time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())


def load_experience() -> dict:
    return json.loads(EXP_PATH.read_text())


def resolve_ca_from_url(url: str, timeout: float = 15.0) -> tuple[str | None, list[str]]:
    """Fetch page / common agent files; return first plausible CA + candidates."""
    candidates: list[str] = []
    urls = [url]
    base = url.rstrip("/")
    for suffix in ("/llms.txt", "/skill.md", "/agent.json", "/abi.json", "/config.js"):
        if not url.endswith(suffix):
            urls.append(base + suffix)
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "bsc-mint-kit/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read(400_000).decode("utf-8", "replace")
            found = CA_RE.findall(text)
            for a in found:
                al = a.lower()
                if al not in {c.lower() for c in candidates}:
                    candidates.append(a)
        except Exception:  # noqa: BLE001
            continue
    # Prefer non-registry / non-USDT known system addresses
    skip = {
        "0x60b9262456de011f7d15a54cdd8c48baaa8b022f",  # agent id registry
        "0x55d398326f99059ff775485246999027b3197955",  # USDT
        "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
        "0x0000000000000000000000000000000000000000",
    }
    for c in candidates:
        if c.lower() not in skip:
            return c, candidates
    return (candidates[0] if candidates else None), candidates


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    uni = len(a | b)
    return inter / uni if uni else 0.0


def match_experience(exp: dict, ca: str, code_hex: str, present_sels: set[str]) -> dict:
    projects = exp.get("projects") or []
    ca_l = ca.lower()
    code = code_hex[2:] if code_hex.startswith("0x") else code_hex
    bhash = hashlib.sha256(bytes.fromhex(code)).hexdigest() if code and code != "" else None
    prefix = bhash[:16] if bhash else None

    exact = next((p for p in projects if (p.get("ca") or "").lower() == ca_l), None)
    if exact:
        return {
            "mode": "exact_ca",
            "project_id": exact["id"],
            "name": exact.get("name"),
            "confidence": exact.get("confidence", 0.9),
            "mintMethod": exact.get("mintMethod"),
            "price": exact.get("price"),
            "eligibility": exact.get("eligibility"),
            "statusReads": exact.get("statusReads"),
            "selectors": exact.get("selectors"),
            "bytecodePrefix16": prefix,
            "notes": exact.get("notes"),
            "source_files": exact.get("source_files"),
        }

    by_prefix = [p for p in projects if p.get("bytecodePrefix16") and p["bytecodePrefix16"] == prefix]
    if by_prefix:
        p = by_prefix[0]
        return {
            "mode": "bytecode_prefix",
            "project_id": p["id"],
            "name": p.get("name"),
            "confidence": min(0.85, float(p.get("confidence", 0.8))),
            "mintMethod": p.get("mintMethod"),
            "price": p.get("price"),
            "eligibility": p.get("eligibility"),
            "statusReads": p.get("statusReads"),
            "selectors": p.get("selectors"),
            "bytecodePrefix16": prefix,
            "notes": "bytecode family match — re-verify address/price/params",
            "source_files": p.get("source_files"),
        }

    best = None
    best_score = 0.0
    for p in projects:
        hints = (p.get("matchHints") or {}).get("selectorSet") or []
        sels = {s.lower() for s in hints if s}
        if not sels:
            sels = {str(v).lower() for v in (p.get("selectors") or {}).values() if v}
        score = jaccard(present_sels, sels)
        if score > best_score:
            best_score = score
            best = p
    if best and best_score >= 0.5:
        return {
            "mode": "selector_jaccard",
            "project_id": best["id"],
            "name": best.get("name"),
            "confidence": round(0.5 + 0.4 * best_score, 3),
            "score": round(best_score, 3),
            "mintMethod": best.get("mintMethod"),
            "price": best.get("price"),
            "eligibility": best.get("eligibility"),
            "statusReads": best.get("statusReads"),
            "selectors": best.get("selectors"),
            "bytecodePrefix16": prefix,
            "notes": "selector-set match — must re-verify; escalate if status reads fail",
            "source_files": best.get("source_files"),
        }

    return {
        "mode": "none",
        "project_id": None,
        "confidence": 0.0,
        "bytecodePrefix16": prefix,
        "bytecodeSha256": bhash,
        "notes": "unfamiliar — escalate to AI / ezbot-project-research after raw selector scan",
    }


def probe_selectors(code_hex: str) -> dict[str, bool]:
    """Cheap presence check: selector bytes appear in runtime bytecode."""
    raw = (code_hex[2:] if code_hex.startswith("0x") else code_hex).lower()
    out = {}
    for sig in COMMON_MINT_SIGS + COMMON_STATUS_SIGS:
        sel = selector(sig)[2:]
        out[sig] = sel in raw
    return out


def build_read_jobs(ca: str, match: dict, wallet: str | None, present: dict[str, bool]) -> list[dict]:
    jobs = [
        {"id": "code", "kind": "code", "to": ca},
        {"id": "eip1967", "kind": "storage", "to": ca, "slot": EIP1967_IMPL_SLOT},
    ]
    # Always try common status + matched statusReads / eligibility reads
    sigs: list[str] = []
    for s in COMMON_STATUS_SIGS:
        if present.get(s):
            sigs.append(s)
    for s in match.get("statusReads") or []:
        if s not in sigs:
            sigs.append(s)
    for s in (match.get("eligibility") or {}).get("readFns") or []:
        if s not in sigs:
            sigs.append(s)
    for s in (match.get("price") or {}).get("readFns") or []:
        if s not in sigs:
            sigs.append(s)
    # mint entry presence already known; still try zero-arg views only for calls
    for sig in sigs:
        if "(" not in sig:
            continue
        types = sig[sig.find("(") + 1 : sig.rfind(")")]
        try:
            if types.strip() == "":
                data = encode_call(sig)
                jobs.append({"id": f"call:{sig}", "kind": "call", "to": ca, "data": data})
            elif types.strip() == "address" and wallet:
                data = encode_call(sig, wallet)
                jobs.append({"id": f"call:{sig}", "kind": "call", "to": ca, "data": data, "from": wallet})
            # skip complex tuples like info() returns in decode; still call info() if zero-arg
        except Exception:  # noqa: BLE001
            continue
    # info() is zero-arg even if return is tuple
    if present.get("info()") and "call:info()" not in {j["id"] for j in jobs}:
        jobs.append({"id": "call:info()", "kind": "call", "to": ca, "data": encode_call("info()")})
    return jobs


def summarize_reads(results: dict, present: dict) -> dict:
    reads = {}
    for k, v in results.items():
        if not k.startswith("call:"):
            continue
        sig = k[len("call:") :]
        if isinstance(v, dict) and "error" in v:
            reads[sig] = {"error": v["error"]}
            continue
        entry: dict = {"raw": v}
        if sig in ("paused()", "publicMintOpen()") or sig.endswith("Open()"):
            entry["bool"] = decode_bool(v)
        elif sig in ("totalSupply()", "maxSupply()", "mintPrice()", "mintPriceWei()", "price()", "freeMinted()", "mintOpensAt()"):
            entry["uint"] = decode_uint(v)
        reads[sig] = entry
    reads["_selector_presence"] = {k: v for k, v in present.items() if v}
    return reads


def risk_check(code_hex: str, match: dict, reads: dict) -> list[dict]:
    risks = []
    if not code_hex or code_hex in ("0x", "0x0"):
        risks.append({"level": "critical", "code": "no_code", "msg": "地址无合约代码"})
    if match.get("mode") == "none":
        risks.append({"level": "warn", "code": "unfamiliar", "msg": "无历史经验匹配，需人工/AI 分析"})
    po = reads.get("publicMintOpen()", {})
    if po.get("bool") is False:
        risks.append({"level": "high", "code": "not_open", "msg": "publicMintOpen=false"})
    paused = reads.get("paused()", {})
    if paused.get("bool") is True:
        risks.append({"level": "high", "code": "paused", "msg": "paused=true"})
    if match.get("mode") != "exact_ca" and match.get("confidence", 0) < 0.7:
        risks.append({"level": "info", "code": "reverify", "msg": "非精确 CA 命中：价格/参数必须重核"})
    return risks


def ready_flag(match: dict, risks: list, reads: dict) -> bool:
    if any(r["level"] in ("critical", "high") for r in risks):
        return False
    if match.get("mode") == "none":
        return False
    mm = match.get("mintMethod") or {}
    if not mm.get("selector") and not mm.get("signature"):
        return False
    # if we have publicMintOpen and it's true, or no such read
    po = reads.get("publicMintOpen()", {})
    if "bool" in po and po["bool"] is False:
        return False
    return True


def ox_baw_preview_path(ca: str, match: dict, wallet: str | None) -> dict:
    mm = match.get("mintMethod") or {}
    sel = mm.get("selector")
    sig = mm.get("signature") or ""
    data = None
    if sel and (not sig or sig.endswith("()")):
        data = sel if sel.startswith("0x") else "0x" + sel
    elif sig == "mint(uint256)":
        qty = 1
        args = mm.get("argsTemplate") or [1]
        if args:
            qty = int(args[0])
        data = encode_call("mint(uint256)", qty)
    elif sig == "claim()":
        data = encode_call("claim()")
    elif sig == "claimFree()":
        data = encode_call("claimFree()")
    value = "0"
    if mm.get("valueMode") not in (None, "zero"):
        value = "<RE-READ price wei before preview>"
    cmd = None
    if data and wallet and value == "0":
        cmd = (
            "ox-baw contract-call preview --binanceChainId 56 "
            f"--from {wallet} --to {ca} --value 0 --inputData {data} --json"
        )
    return {
        "preview_only": True,
        "execute_forbidden": True,
        "calldata": data,
        "value_wei": value,
        "cmd": cmd,
        "note": "仅 preview；需 BINANCE_BAW_DIR / 已登录 ox-baw。禁止 execute。",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="BSC mint precheck (read-only)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ca", help="mint contract address")
    g.add_argument("--url", help="project URL to resolve CA from")
    ap.add_argument("--wallet", default=os.environ.get("MINT_WALLET") or "")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    stages: dict[str, float] = {}

    url_meta = {}
    ca = args.ca
    if args.url:
        t = time.perf_counter()
        ca, cands = resolve_ca_from_url(args.url)
        stages["resolve_url_ms"] = round((time.perf_counter() - t) * 1000, 1)
        url_meta = {"url": args.url, "candidates": cands}
        if not ca:
            report = {
                "ok": False,
                "error": "could_not_resolve_ca",
                "url_meta": url_meta,
                "stage_timings_ms": stages,
                "checked_at": now_shanghai_label(),
                "ready_for_confirm": False,
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            return 2

    ca = ca.strip()
    if not CA_RE.fullmatch(ca):
        print(json.dumps({"ok": False, "error": "invalid_ca", "ca": ca}), file=sys.stderr)
        return 2

    wallet = args.wallet.strip() or None
    exp = load_experience()

    t = time.perf_counter()
    code = get_code(ca)
    stages["get_code_ms"] = round((time.perf_counter() - t) * 1000, 1)

    t = time.perf_counter()
    present = probe_selectors(code)
    present_sels = {selector(s).lower() for s, ok in present.items() if ok}
    match = match_experience(exp, ca, code, present_sels)
    stages["match_ms"] = round((time.perf_counter() - t) * 1000, 1)

    t = time.perf_counter()
    jobs = build_read_jobs(ca, match, wallet, present)
    # code already fetched; still include for consistency but we can skip duplicate
    jobs = [j for j in jobs if j["id"] != "code"]
    results = parallel_calls(jobs)
    stages["parallel_reads_ms"] = round((time.perf_counter() - t) * 1000, 1)

    impl = impl_from_eip1967(results.get("eip1967", "0x") if not isinstance(results.get("eip1967"), dict) else "0x")
    reads = summarize_reads(results, present)
    risks = risk_check(code, match, reads)
    ready = ready_flag(match, risks, reads)
    baw = ox_baw_preview_path(ca, match, wallet)

    stages["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    code_len = (len(code) - 2) // 2 if code and code.startswith("0x") else 0

    report = {
        "ok": True,
        "chainId": 56,
        "ca": ca,
        "wallet": wallet,
        "checked_at": now_shanghai_label(),
        "url_meta": url_meta or None,
        "code_len": code_len,
        "implementation": impl,
        "experience_match": match,
        "reads": reads,
        "risks": risks,
        "ready_for_confirm": ready,
        "escalate_ai": match.get("mode") == "none" or (match.get("confidence") or 0) < 0.5,
        "ox_baw_preview": baw,
        "ox_baw_preview_cmd": baw.get("cmd"),
        "stage_timings_ms": stages,
        "safety": {
            "broadcast": False,
            "sign": False,
            "approve": False,
            "execute": False,
            "mode": "read_only_dry_run",
        },
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
