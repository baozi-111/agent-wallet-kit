"""BSC JSON-RPC helpers for read-only mint precheck. Never sends txs."""
from __future__ import annotations

import json
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

# Prefer env, then public BSC seeds used elsewhere on this box.
DEFAULT_RPCS = [
    os.environ.get("BSC_RPC") or "",
    os.environ.get("BSC_RPC_URL") or "",
    "https://bsc-dataseed.bnbchain.org",
    "https://bsc-rpc.publicnode.com",
    "https://bsc-dataseed1.binance.org",
]
RPCS = [u for u in DEFAULT_RPCS if u]

EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"

try:
    from Crypto.Hash import keccak as _keccak

    def keccak256(data: bytes) -> bytes:
        return _keccak.new(digest_bits=256, data=data).digest()

except ImportError:  # pragma: no cover
    import hashlib

    def keccak256(data: bytes) -> bytes:
        # pysha3 may be absent; prefer pycryptodome. Fallback raises.
        try:
            import sha3  # type: ignore

            return sha3.keccak_256(data).digest()
        except ImportError as e:
            raise RuntimeError("need pycryptodome (Crypto.Hash.keccak)") from e


def selector(sig: str) -> str:
    return "0x" + keccak256(sig.encode()).hex()[:8]


def _rpc_once(url: str, method: str, params: list, timeout: float = 20.0) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.load(resp)
    if "error" in out:
        raise RuntimeError(f"RPC error from {url}: {out['error']}")
    return out.get("result")


def rpc(method: str, params: list, timeout: float = 20.0) -> Any:
    last = None
    for url in RPCS:
        try:
            return _rpc_once(url, method, params, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            last = e
            continue
    raise RuntimeError(f"all RPC endpoints failed for {method}: {last}")


def eth_call(to: str, data: str, frm: str | None = None, block: str = "latest") -> str:
    o: dict[str, str] = {"to": to, "data": data}
    if frm:
        o["from"] = frm
    return rpc("eth_call", [o, block])


def get_code(addr: str, block: str = "latest") -> str:
    return rpc("eth_getCode", [addr, block]) or "0x"


def get_storage(addr: str, slot: str, block: str = "latest") -> str:
    return rpc("eth_getStorageAt", [addr, slot, block]) or "0x"


def pad_addr(a: str) -> str:
    return a.lower().replace("0x", "").rjust(64, "0")


def pad_uint(n: int) -> str:
    return hex(n)[2:].rjust(64, "0")


def encode_call(sig: str, *args: Any) -> str:
    """Encode simple calls: address / uint256 / bool / empty. No dynamic types."""
    sel = selector(sig)[2:]
    parts = []
    # parse types from signature
    if "(" not in sig:
        raise ValueError(sig)
    types = sig[sig.find("(") + 1 : sig.rfind(")")].strip()
    type_list = [t.strip() for t in types.split(",")] if types else []
    if len(type_list) == 1 and type_list[0] == "":
        type_list = []
    if len(args) != len(type_list):
        raise ValueError(f"{sig} expects {len(type_list)} args, got {len(args)}")
    for t, v in zip(type_list, args):
        if t == "address":
            parts.append(pad_addr(str(v)))
        elif t.startswith("uint") or t.startswith("int"):
            parts.append(pad_uint(int(v)))
        elif t == "bool":
            parts.append(pad_uint(1 if v else 0))
        else:
            raise NotImplementedError(f"type {t} not supported in encode_call")
    return "0x" + sel + "".join(parts)


def parallel_calls(jobs: list[dict], max_workers: int = 12) -> dict[str, Any]:
    """jobs: [{id, kind: call|code|storage, ...}]. Returns {id: result|error}."""

    def run(job: dict) -> tuple[str, Any]:
        jid = job["id"]
        try:
            kind = job["kind"]
            if kind == "call":
                return jid, eth_call(job["to"], job["data"], job.get("from"))
            if kind == "code":
                return jid, get_code(job["to"])
            if kind == "storage":
                return jid, get_storage(job["to"], job["slot"])
            raise ValueError(kind)
        except Exception as e:  # noqa: BLE001
            return jid, {"error": str(e)}

    out: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(run, j) for j in jobs]
        for f in as_completed(futs):
            jid, val = f.result()
            out[jid] = val
    return out


def impl_from_eip1967(storage_hex: str) -> str | None:
    if not storage_hex or storage_hex in ("0x", "0x" + "0" * 64):
        return None
    h = storage_hex.lower().replace("0x", "").rjust(64, "0")
    if h == "0" * 64:
        return None
    return "0x" + h[-40:]


def decode_bool(hexdata: str) -> bool | None:
    if not hexdata or hexdata == "0x" or isinstance(hexdata, dict):
        return None
    try:
        return int(hexdata, 16) != 0
    except ValueError:
        return None


def decode_uint(hexdata: str) -> int | None:
    if not hexdata or hexdata == "0x" or isinstance(hexdata, dict):
        return None
    try:
        return int(hexdata, 16)
    except ValueError:
        return None


COMMON_MINT_SIGS = [
    "mint()",
    "claim()",
    "claimFree()",
    "mint(uint256)",
    "mintWithBnb(uint256)",
    "mint(uint256,address)",
    "mint(uint256,address,uint256)",
    "publicMint(uint256)",
    "freeMint()",
    "safeMint(address)",
]

COMMON_STATUS_SIGS = [
    "paused()",
    "publicMintOpen()",
    "mintOpensAt()",
    "totalSupply()",
    "maxSupply()",
    "mintPrice()",
    "mintPriceWei()",
    "price()",
    "info()",
    "freeMinted()",
]
