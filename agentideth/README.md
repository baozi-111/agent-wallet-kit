# AgentID ETH paid mint template

Generalized from a one-handle `mint15` script. The profile, payer, and share count are environment variables. There is no built-in handle.

```bash
export OX_WALLET=your-profile
export FROM=0xYourAddress
export SHARES=15
# optional: AGENTID_HANDLE, AGENTID_MINT, ETH_RPC, AGENTID_MINT_START
bash mint_paid.sh
```

The script:

1. Waits only if `AGENTID_MINT_START` is set.
2. Checks that `FROM` has ETH.
3. Requests a paid voucher from `AGENTID_API` (default `https://agentideth.com/api/voucher`) using `AGENTID_HANDLE` or `OX_WALLET`.
4. Quotes `quoteEth(uint256)` with `cast`, adds 8% headroom, and writes calldata under `out/` (gitignored).
5. Runs `ox-baw contract-call preview` on Ethereum (`binanceChainId` 1) when the CLI is on `PATH`.

It stops there. Set `AGENTID_EXECUTE=1` only after you have read the preview and intend to pay. The script never reads a private key; signing stays inside the BAW profile selected by `OX_WALLET`.

Requires Foundry `cast` on `PATH`. Preview and execute require `ox-baw` (override with `BAW_BIN`).
