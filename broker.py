"""
execution/broker.py
Alpaca order execution engine.
- Places market / limit / bracket orders
- Polls for fills and updates positions
- Supports paper and live trading via env var
"""

import os
import time
import alpaca_trade_api as tradeapi
from loguru import logger
from dotenv import load_dotenv

load_dotenv()


class AlpacaBroker:

    def __init__(self):
        self.api = tradeapi.REST(
            key_id=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
            base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        )
        self.env = os.getenv("ENV", "paper")
        logger.info(f"Broker initialized in {self.env.upper()} mode")
        self._verify_connection()

    def _verify_connection(self):
        try:
            account = self.api.get_account()
            logger.success(f"Connected to Alpaca | "
                           f"Equity: ${float(account.equity):,.2f} | "
                           f"Cash: ${float(account.cash):,.2f} | "
                           f"Buying Power: ${float(account.buying_power):,.2f}")
        except Exception as e:
            logger.error(f"Alpaca connection failed: {e}")
            raise

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        try:
            a = self.api.get_account()
            return {
                "equity": float(a.equity),
                "cash": float(a.cash),
                "buying_power": float(a.buying_power),
                "portfolio_value": float(a.portfolio_value),
                "day_trade_count": int(a.daytrade_count),
                "pattern_day_trader": a.pattern_day_trader,
                "trading_blocked": a.trading_blocked,
                "account_blocked": a.account_blocked,
            }
        except Exception as e:
            logger.error(f"get_account error: {e}")
            return {}

    def get_positions(self) -> list[dict]:
        try:
            positions = self.api.list_positions()
            return [
                {
                    "symbol": p.symbol,
                    "qty": float(p.qty),
                    "avg_cost": float(p.avg_entry_price),
                    "current_price": float(p.current_price),
                    "market_value": float(p.market_value),
                    "unrealized_pnl": float(p.unrealized_pl),
                    "unrealized_pnl_pct": float(p.unrealized_plpc) * 100,
                }
                for p in positions
            ]
        except Exception as e:
            logger.error(f"get_positions error: {e}")
            return []

    def is_market_open(self) -> bool:
        try:
            clock = self.api.get_clock()
            return clock.is_open
        except Exception as e:
            logger.error(f"is_market_open error: {e}")
            return False

    # ── Orders ────────────────────────────────────────────────────────────────

    def buy_market(self, symbol: str, qty: int, strategy: str = "") -> dict | None:
        """Place a market buy order."""
        if qty <= 0:
            logger.warning(f"Invalid qty {qty} for {symbol}")
            return None
        try:
            logger.info(f"Placing BUY {qty} {symbol} (market) [{strategy}]")
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                type="market",
                time_in_force="day",
            )
            logger.success(f"Order submitted: {order.id} | {qty} {symbol}")
            return {
                "order_id": order.id,
                "symbol": symbol,
                "side": "buy",
                "qty": qty,
                "status": order.status,
            }
        except Exception as e:
            logger.error(f"buy_market error {symbol}: {e}")
            return None

    def sell_market(self, symbol: str, qty: int, strategy: str = "") -> dict | None:
        """Place a market sell order."""
        if qty <= 0:
            return None
        try:
            logger.info(f"Placing SELL {qty} {symbol} (market) [{strategy}]")
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="market",
                time_in_force="day",
            )
            logger.success(f"Sell order submitted: {order.id}")
            return {
                "order_id": order.id,
                "symbol": symbol,
                "side": "sell",
                "qty": qty,
                "status": order.status,
            }
        except Exception as e:
            logger.error(f"sell_market error {symbol}: {e}")
            return None

    def buy_bracket(self, symbol: str, qty: int,
                    stop_loss: float, take_profit: float,
                    strategy: str = "") -> dict | None:
        """
        Bracket order — automatically sets stop-loss and take-profit
        on the exchange. Falls back to plain buy + stop order if bracket fails.
        """
        if qty <= 0:
            return None
        try:
            logger.info(f"Placing BRACKET BUY {qty} {symbol} "
                        f"SL=${stop_loss:.2f} TP=${take_profit:.2f}")
            order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                type="market",
                time_in_force="day",
                order_class="bracket",
                stop_loss={"stop_price": str(round(stop_loss, 2))},
                take_profit={"limit_price": str(round(take_profit, 2))},
            )
            logger.success(f"Bracket order placed: {order.id} | "
                           f"SL=${stop_loss:.2f} TP=${take_profit:.2f}")
            return {
                "order_id": order.id,
                "symbol": symbol,
                "side": "buy",
                "qty": qty,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "status": order.status,
                "order_type": "bracket",
            }
        except Exception as e:
            logger.warning(f"Bracket order failed for {symbol}: {e} — trying plain buy + stop")
            return self._buy_with_stop_fallback(symbol, qty, stop_loss, take_profit, strategy)

    def _buy_with_stop_fallback(self, symbol: str, qty: int,
                                 stop_loss: float, take_profit: float,
                                 strategy: str = "") -> dict | None:
        """
        Fallback when bracket order fails.
        Places plain market buy, then attaches a separate stop-loss order.
        """
        try:
            # Step 1 — plain market buy
            logger.info(f"Fallback: plain BUY {qty} {symbol}")
            buy_order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                type="market",
                time_in_force="day",
            )
            logger.success(f"Plain buy placed: {buy_order.id}")

            # Step 2 — wait for fill so stop order references real position
            import time
            time.sleep(2)

            # Step 3 — attach stop-loss order
            logger.info(f"Attaching stop-loss @ ${stop_loss:.2f}")
            stop_order = self.api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="stop",
                stop_price=str(round(stop_loss, 2)),
                time_in_force="gtc",   # good till cancelled
            )
            logger.success(f"Stop-loss order placed: {stop_order.id} @ ${stop_loss:.2f}")

            return {
                "order_id": buy_order.id,
                "stop_order_id": stop_order.id,
                "symbol": symbol,
                "side": "buy",
                "qty": qty,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "status": buy_order.status,
                "order_type": "plain_with_stop",
            }
        except Exception as e:
            logger.error(f"Fallback buy also failed for {symbol}: {e}")
            return None

    def sell_all(self, symbol: str) -> dict | None:
        """Close entire position in a symbol."""
        try:
            positions = {p["symbol"]: p for p in self.get_positions()}
            if symbol not in positions:
                logger.warning(f"No position to close for {symbol}")
                return None
            qty = positions[symbol]["qty"]
            return self.sell_market(symbol, int(qty))
        except Exception as e:
            logger.error(f"sell_all error {symbol}: {e}")
            return None

    def cancel_all_orders(self):
        """Emergency cancel all open orders."""
        try:
            self.api.cancel_all_orders()
            logger.warning("All open orders cancelled")
        except Exception as e:
            logger.error(f"cancel_all_orders error: {e}")

    def liquidate_all(self):
        """Emergency liquidate all positions."""
        logger.critical("EMERGENCY LIQUIDATION — closing all positions")
        try:
            self.api.close_all_positions()
            logger.critical("All positions closed")
        except Exception as e:
            logger.error(f"liquidate_all error: {e}")

    def wait_for_fill(self, order_id: str, timeout: int = 30) -> float | None:
        """Poll for fill price. Returns filled price or None."""
        for _ in range(timeout):
            try:
                order = self.api.get_order(order_id)
                if order.status == "filled":
                    return float(order.filled_avg_price)
                if order.status in ("cancelled", "expired", "rejected"):
                    logger.warning(f"Order {order_id} ended with status: {order.status}")
                    return None
                time.sleep(1)
            except Exception as e:
                logger.error(f"wait_for_fill error: {e}")
                time.sleep(1)
        logger.warning(f"Order {order_id} not filled within {timeout}s")
        return None
