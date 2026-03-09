"""
КРОК 5: Trade Executor — buy/sell via Jupiter + Jito anti-sandwich.

In paper trading mode, simulates trades without sending transactions.
"""

from __future__ import annotations

import logging
import time

from config import Config
from models import PoolInfo, TradeRecord
from wallet_pool import WalletPool
from api_clients.jupiter import JupiterClient
from api_clients.jito import JitoClient
from utils import sol_to_lamports

logger = logging.getLogger(__name__)


class TradeExecutor:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.jupiter = JupiterClient(
            api_key=cfg.jupiter_api_key,
            quote_url=cfg.jupiter_quote_url,
            swap_url=cfg.jupiter_swap_url,
        )
        self.jito = JitoClient(cfg.jito_endpoint) if cfg.use_jito else None
        if cfg.paper_trading:
            self.wallet_pool = WalletPool.generate(1)
        else:
            self.wallet_pool = WalletPool.from_private_key(cfg.private_key)

    async def buy(self, pool: PoolInfo, amount_sol: float) -> TradeRecord | None:
        """Execute a buy: SOL -> token."""
        wallet = self.wallet_pool.next_wallet()
        wallet_pubkey = str(wallet.pubkey())

        logger.info(
            "BUY %s: %.3f SOL via %s (wallet: %s)",
            pool.token_symbol or pool.token_mint[:12],
            amount_sol,
            "paper" if self.cfg.paper_trading else "live",
            wallet_pubkey[:12],
        )

        amount_lamports = sol_to_lamports(amount_sol)

        # Get quote
        quote = await self.jupiter.get_quote(
            self.cfg.SOL_MINT,
            pool.token_mint,
            amount_lamports,
            self.cfg.max_slippage_bps,
        )
        if not quote:
            logger.warning("Failed to get buy quote for %s", pool.token_mint[:12])
            return None

        tokens_out = int(quote.get("outAmount", 0))
        if tokens_out == 0:
            logger.warning("Buy quote returned 0 tokens for %s", pool.token_mint[:12])
            return None

        price = amount_sol / tokens_out if tokens_out > 0 else 0

        trade = TradeRecord(
            token_mint=pool.token_mint,
            token_symbol=pool.token_symbol,
            side="BUY",
            amount_sol=amount_sol,
            token_amount=tokens_out,
            price_per_token=price,
            wallet_address=wallet_pubkey,
        )

        if self.cfg.paper_trading:
            trade.tx_signature = f"paper_{int(time.time())}_{pool.token_mint[:8]}"
            logger.info(
                "PAPER BUY: %s tokens=%d price=%.10f",
                pool.token_symbol or pool.token_mint[:12], tokens_out, price,
            )
            return trade

        # Live execution: build and send transaction
        swap_data = await self.jupiter.build_swap_tx(quote, wallet_pubkey)
        if not swap_data:
            logger.error("Failed to build swap TX for %s", pool.token_mint[:12])
            return None

        swap_tx_b64 = swap_data.get("swapTransaction", "")
        if not swap_tx_b64:
            logger.error("No swapTransaction in response for %s", pool.token_mint[:12])
            return None

        # Deserialize, sign, and send
        try:
            import base64
            from solders.transaction import VersionedTransaction

            tx_bytes = base64.b64decode(swap_tx_b64)
            tx = VersionedTransaction.from_bytes(tx_bytes)

            # Sign the transaction
            signed_tx = VersionedTransaction(tx.message, [wallet])
            signed_bytes = bytes(signed_tx)

            # Send via Jito (anti-sandwich) or direct RPC
            if self.jito and self.cfg.use_jito:
                sig = await self.jito.send_transaction(signed_bytes)
            else:
                # Fallback: send via regular RPC (not recommended)
                import aiohttp
                import base58 as b58
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "jsonrpc": "2.0", "id": 1,
                        "method": "sendTransaction",
                        "params": [
                            b58.b58encode(signed_bytes).decode(),
                            {"encoding": "base58", "skipPreflight": True},
                        ],
                    }
                    async with session.post(self.cfg.rpc_http, json=payload) as resp:
                        data = await resp.json()
                        sig = data.get("result", "")

            trade.tx_signature = sig
            logger.info("BUY TX sent: %s", sig[:20] if sig else "FAILED")
        except Exception as e:
            logger.exception("Failed to sign/send buy TX: %s", e)
            return None

        return trade

    async def sell(
        self, token_mint: str, token_amount: int, wallet_pubkey: str
    ) -> TradeRecord | None:
        """Execute a sell: token -> SOL."""
        logger.info(
            "SELL %s: %d tokens (wallet: %s)",
            token_mint[:12], token_amount, wallet_pubkey[:12],
        )

        quote = await self.jupiter.get_quote(
            token_mint,
            self.cfg.SOL_MINT,
            token_amount,
            self.cfg.max_slippage_bps,
        )
        if not quote:
            logger.warning("Failed to get sell quote for %s", token_mint[:12])
            return None

        sol_out = int(quote.get("outAmount", 0))
        sol_amount = sol_out / 1_000_000_000

        price_per_token = sol_amount / token_amount if token_amount > 0 else 0

        trade = TradeRecord(
            token_mint=token_mint,
            side="SELL",
            amount_sol=sol_amount,
            token_amount=token_amount,
            price_per_token=price_per_token,
            wallet_address=wallet_pubkey,
        )

        if self.cfg.paper_trading:
            trade.tx_signature = f"paper_sell_{int(time.time())}_{token_mint[:8]}"
            logger.info("PAPER SELL: %s sol_out=%.4f", token_mint[:12], sol_amount)
            return trade

        # Live sell execution would follow same pattern as buy
        # (build_swap_tx → sign → send via Jito)
        swap_data = await self.jupiter.build_swap_tx(quote, wallet_pubkey)
        if not swap_data:
            return None

        try:
            import base64
            from solders.transaction import VersionedTransaction

            swap_tx_b64 = swap_data.get("swapTransaction", "")
            tx_bytes = base64.b64decode(swap_tx_b64)
            tx = VersionedTransaction.from_bytes(tx_bytes)

            # Find the wallet keypair
            wallet_kp = None
            for kp in self.wallet_pool.keypairs:
                if str(kp.pubkey()) == wallet_pubkey:
                    wallet_kp = kp
                    break
            if not wallet_kp:
                logger.error("Wallet %s not found in pool", wallet_pubkey[:12])
                return None

            signed_tx = VersionedTransaction(tx.message, [wallet_kp])
            signed_bytes = bytes(signed_tx)

            if self.jito and self.cfg.use_jito:
                sig = await self.jito.send_transaction(signed_bytes)
            else:
                sig = ""  # fallback not implemented for sell

            trade.tx_signature = sig
        except Exception as e:
            logger.exception("Failed to sign/send sell TX: %s", e)
            return None

        return trade

    async def close(self) -> None:
        await self.jupiter.close()
        if self.jito:
            await self.jito.close()
