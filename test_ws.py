"""Quick test: does blockSubscribe vs logsSubscribe work on our Helius plan?"""
import asyncio, json, os
from dotenv import load_dotenv
from websockets import connect

load_dotenv()
WSS = os.getenv("RPC_WSS")
PUMPSWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"

async def test_logs_subscribe():
    print(f"Connecting to {WSS[:40]}...")
    async with connect(WSS, ping_interval=20, ping_timeout=20) as ws:
        # Test 1: logsSubscribe
        await ws.send(json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "logsSubscribe",
            "params": [
                {"mentions": [PUMPSWAP]},
                {"commitment": "confirmed"},
            ],
        }))
        confirm = await asyncio.wait_for(ws.recv(), timeout=10)
        print(f"logsSubscribe response: {confirm}")

        print("Waiting for log events (30s)...")
        count = 0
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(msg)
                count += 1
                logs = data.get("params", {}).get("result", {}).get("value", {}).get("logs", [])
                sig = data.get("params", {}).get("result", {}).get("value", {}).get("signature", "?")
                print(f"  [{count}] sig={sig[:16]}  logs_count={len(logs)}")
                if count >= 5:
                    break
        except asyncio.TimeoutError:
            print(f"Timeout after 30s. Got {count} events.")

async def test_block_subscribe():
    print(f"\nTesting blockSubscribe...")
    async with connect(WSS, ping_interval=20, ping_timeout=20) as ws:
        await ws.send(json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "blockSubscribe",
            "params": [
                {"mentionsAccountOrProgram": PUMPSWAP},
                {"commitment": "confirmed", "encoding": "jsonParsed",
                 "showRewards": False, "transactionDetails": "full",
                 "maxSupportedTransactionVersion": 0},
            ],
        }))
        confirm = await asyncio.wait_for(ws.recv(), timeout=10)
        print(f"blockSubscribe response: {confirm}")

        if "error" in confirm.lower():
            print("blockSubscribe NOT supported!")
            return

        print("Waiting for block events (30s)...")
        count = 0
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(msg)
                count += 1
                print(f"  [{count}] keys={list(data.keys())[:5]}")
                if count >= 3:
                    break
        except asyncio.TimeoutError:
            print(f"Timeout after 30s. Got {count} block events.")

asyncio.run(test_logs_subscribe())
asyncio.run(test_block_subscribe())
