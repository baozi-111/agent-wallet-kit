#!/usr/bin/env python3
"""Hot path: URL/CA → mint cost + sell quote + wallet BNB in parallel. No txs."""
from __future__ import annotations
import argparse, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from Crypto.Hash import keccak  # noqa: E402

try:
    from lib_rpc import rpc_call, eth_call  # type: ignore
except Exception:
    RPCs = [
        "https://bsc.publicnode.com",
        "https://bsc-dataseed1.binance.org/",
        "https://bsc-dataseed2.binance.org/",
    ]

    def rpc_call(method, params, timeout=8):
        last = None
        for url in RPCs:
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    j = json.loads(r.read())
                if "error" in j:
                    raise RuntimeError(j["error"])
                return j["result"]
            except Exception as e:
                last = e
        raise last

    def eth_call(to, data, from_=None, value=None):
        tx = {"to": to, "data": data}
        if from_:
            tx["from"] = from_
        if value is not None:
            tx["value"] = hex(value)
        return rpc_call("eth_call", [tx, "latest"])


def sel(sig: str) -> str:
    k = keccak.new(digest_bits=256)
    k.update(sig.encode())
    return "0x" + k.hexdigest()[:8]


def pad_uint(n: int) -> str:
    return hex(n)[2:].zfill(64)


def pad_addr(a: str) -> str:
    return a[2:].lower().zfill(64)


def load_experience():
    p = ROOT / "experience" / "index.json"
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("projects") or []


def match_exp(ca: str):
    ca_l = ca.lower()
    for p in load_experience():
        if (p.get("ca") or "").lower() == ca_l or (p.get("tokenCa") or "").lower() == ca_l:
            return p
        for c in p.get("contracts") or []:
            if str(c).lower() == ca_l:
                return p
    return None


def quote_mint_cost(mint: str, shares: int, wallet: str | None):
    """Try quote(uint256) then currentPrice()*shares then binary search mint()."""
    t0 = time.time()
    out = {"method": None, "cost_wei": None, "cost_bnb": None, "error": None}
    # quote
    try:
        raw = eth_call(mint, sel("quote(uint256)") + pad_uint(shares), from_=wallet)
        if raw and raw != "0x" and len(raw) >= 66:
            vals = [int(raw[2 + i * 64 : 2 + (i + 1) * 64], 16) for i in range(len(raw[2:]) // 64)]
            # pick first plausible BNB-sized value
            for v in vals:
                if 10**12 < v < 10**20:  # 1e-6 .. 100 BNB
                    out.update(method="quote(uint256)", cost_wei=v, cost_bnb=v / 1e18)
                    out["ms"] = round((time.time() - t0) * 1000, 1)
                    return out
    except Exception as e:
        out["quote_err"] = str(e)[:120]
    # currentPrice
    try:
        px = int(eth_call(mint, sel("currentPrice()"), from_=wallet), 16)
        if px > 0:
            v = px * shares
            out.update(method="currentPrice()*n", cost_wei=v, cost_bnb=v / 1e18)
            out["ms"] = round((time.time() - t0) * 1000, 1)
            return out
    except Exception as e:
        out["price_err"] = str(e)[:120]
    out["error"] = "no_quote"
    out["ms"] = round((time.time() - t0) * 1000, 1)
    return out


def pcs_sell_quote(token: str, amount_tokens: float):
    t0 = time.time()
    WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
    FACTORY = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
    amt = int(amount_tokens * 10**18)
    try:
        pair = "0x" + eth_call(FACTORY, sel("getPair(address,address)") + pad_addr(token) + pad_addr(WBNB))[-40:]
        if int(pair, 16) == 0:
            return {"bnb_out": 0, "pair": None, "ms": round((time.time() - t0) * 1000, 1), "error": "no_pair"}
        data = (
            sel("getAmountsOut(uint256,address[])")
            + pad_uint(amt)
            + pad_uint(64)
            + pad_uint(2)
            + pad_addr(token)
            + pad_addr(WBNB)
        )
        raw = eth_call(ROUTER, data)
        b = bytes.fromhex(raw[2:])
        n = int.from_bytes(b[32:64], "big")
        amounts = [int.from_bytes(b[64 + i * 32 : 96 + i * 32], "big") for i in range(n)]
        return {
            "bnb_out": amounts[-1] / 1e18,
            "pair": pair,
            "ms": round((time.time() - t0) * 1000, 1),
        }
    except Exception as e:
        return {"bnb_out": None, "error": str(e)[:160], "ms": round((time.time() - t0) * 1000, 1)}


def baw_sell_quote(token: str, amount: float):
    t0 = time.time()
    import subprocess

    env = os.environ.copy()
    cmd = [
        "ox-baw",
        "market-order",
        "quote",
        "--fromTokenQty",
        str(amount),
        "--fromToken",
        token,
        "--toToken",
        "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "--binanceChainId",
        "56",
        "--slippage",
        "8",
        "--json",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=25)
        j = json.loads(r.stdout or "{}")
        if j.get("success"):
            d = j["data"]
            return {
                "bnb_out": float(d.get("toCoinAmount") or 0),
                "ms": round((time.time() - t0) * 1000, 1),
                "source": "baw",
            }
        return {"error": j, "ms": round((time.time() - t0) * 1000, 1)}
    except Exception as e:
        return {"error": str(e)[:160], "ms": round((time.time() - t0) * 1000, 1)}


def wallet_bnb(addr: str):
    t0 = time.time()
    try:
        bal = int(rpc_call("eth_getBalance", [addr, "latest"]), 16) / 1e18
        return {"bnb": bal, "ms": round((time.time() - t0) * 1000, 1)}
    except Exception as e:
        return {"error": str(e)[:120], "ms": round((time.time() - t0) * 1000, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mint", required=True, help="mint contract CA")
    ap.add_argument("--token", required=True, help="token CA received from mint")
    ap.add_argument("--shares", type=int, default=10)
    ap.add_argument("--tokens-per-share", type=float, default=100_000_000)
    ap.add_argument("--wallet", default=os.environ.get("MINT_WALLET", ""))
    args = ap.parse_args()
    t0 = time.time()
    exp = match_exp(args.mint) or match_exp(args.token)
    tokens = args.shares * args.tokens_per_share
    wallet = args.wallet or None

    results = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {
            ex.submit(quote_mint_cost, args.mint, args.shares, wallet): "mint_cost",
            ex.submit(pcs_sell_quote, args.token, tokens): "pcs_sell",
            ex.submit(baw_sell_quote, args.token, tokens): "baw_sell",
        }
        if wallet:
            futs[ex.submit(wallet_bnb, wallet)] = "wallet"
        for f in as_completed(futs):
            results[futs[f]] = f.result()

    cost = (results.get("mint_cost") or {}).get("cost_bnb")
    sell = None
    for k in ("baw_sell", "pcs_sell"):
        v = (results.get(k) or {}).get("bnb_out")
        if v is not None:
            sell = max(sell or 0, v)
    spread = (sell - cost) if (sell is not None and cost is not None) else None
    report = {
        "hot": True,
        "experience_id": (exp or {}).get("id"),
        "mint": args.mint,
        "token": args.token,
        "shares": args.shares,
        "tokens_out_est": tokens,
        "mint_cost_bnb": cost,
        "sell_bnb_est": sell,
        "spread_bnb": spread,
        "go": bool(spread is not None and spread > 0.001 and (not wallet or (results.get("wallet") or {}).get("bnb", 0) > (cost or 0) + 0.002)),
        "stages": results,
        "total_ms": round((time.time() - t0) * 1000, 1),
        "next": "Read-only. This script does not sign or broadcast. If go=true and the operator explicitly authorizes mint+sell, preview then execute in a separate step.",
    }
    outp = ROOT / "out" / "last-fast-arb.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("mint_cost_bnb") is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
