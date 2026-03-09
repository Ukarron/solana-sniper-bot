"""Debug: fetch and inspect a PumpSwap migrate transaction."""
import asyncio, json, os, sys
from dotenv import load_dotenv
import aiohttp

load_dotenv()
RPC = os.getenv("RPC_HTTP")

PUMPSWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
RAYDIUM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
PUMPFUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
SPL_TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
SOL_MINT = "So11111111111111111111111111111111111111112"
SYSTEM_PROGRAMS = {
    PUMPSWAP, RAYDIUM, PUMPFUN, SPL_TOKEN, TOKEN_2022, SOL_MINT,
    "11111111111111111111111111111111",
    "SysvarRent111111111111111111111111111111111",
    "SysvarC1ock11111111111111111111111111111111",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "ComputeBudget111111111111111111111111111111",
    "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",
}

async def fetch_recent_pumpswap_tx():
    async with aiohttp.ClientSession() as session:
        # Use logsSubscribe to find a fresh PumpSwap migrate tx
        from websockets import connect
        print("Connecting to WS to find a migrate tx...")
        async with connect(os.getenv("RPC_WSS"), ping_interval=20) as ws:
            await ws.send(json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "method": "logsSubscribe",
                "params": [{"mentions": [PUMPSWAP]}, {"commitment": "confirmed"}],
            }))
            await asyncio.wait_for(ws.recv(), timeout=10)

            sig = None
            for _ in range(5000):
                msg = await asyncio.wait_for(ws.recv(), timeout=60)
                data = json.loads(msg)
                if "method" not in data:
                    continue
                value = data.get("params", {}).get("result", {}).get("value", {})
                logs = value.get("logs", [])
                logs_text = "\n".join(logs)
                if "migrate" in logs_text.lower() and PUMPSWAP in logs_text:
                    sig = value.get("signature")
                    print(f"Found migrate tx: {sig}")
                    print(f"Logs:\n{logs_text[:500]}")
                    break

            if not sig:
                print("No migrate tx found in 5000 events")
                return

        # Now fetch the full tx
        await asyncio.sleep(2)
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
            "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"}],
        }
        async with session.post(RPC, json=payload) as resp:
            result = await resp.json()
            tx = result.get("result")
            if not tx:
                print("Could not fetch tx!")
                return

            message = tx["transaction"]["message"]
            account_keys = message.get("accountKeys", [])

            print(f"\n=== Account keys ({len(account_keys)}) ===")
            for i, k in enumerate(account_keys):
                pubkey = k if isinstance(k, str) else k.get("pubkey", "")
                signer = ""
                writable = ""
                if isinstance(k, dict):
                    signer = " [SIGNER]" if k.get("signer") else ""
                    writable = " [WRITABLE]" if k.get("writable") else ""
                label = ""
                if pubkey == PUMPSWAP:
                    label = " << PUMPSWAP"
                elif pubkey == PUMPFUN:
                    label = " << PUMPFUN"
                elif pubkey == SPL_TOKEN:
                    label = " << SPL_TOKEN"
                elif pubkey == SOL_MINT:
                    label = " << SOL_MINT"
                elif pubkey in SYSTEM_PROGRAMS:
                    label = " << SYSTEM"
                print(f"  [{i:2d}] {pubkey}{signer}{writable}{label}")

            # Also look at inner instructions for token mint
            meta = tx.get("meta", {})
            inner = meta.get("innerInstructions", [])
            print(f"\n=== Post token balances ===")
            for b in meta.get("postTokenBalances", []):
                print(f"  mint={b.get('mint')} owner={b.get('owner', '')[:16]} amount={b.get('uiTokenAmount', {}).get('uiAmountString', '?')}")

asyncio.run(fetch_recent_pumpswap_tx())
