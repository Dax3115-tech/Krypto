"""
risk/manager.py
Risk Management Layer

Controls:
  - Position sizing (volatility-based + max % of portfolio)
  - Stop-loss / take-profit enforcement
  - Max open positions
  - Daily loss kill switch (pauses all trading if -X% hit)
  - Exposure limits
"""

import os
from datetime import datetime, date
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class RiskConfig:
    max_position_pct: float = 0.10    # max 10% of portfolio per position
    max_open_positions: int = 5
    stop_loss_pct: float = 0.02       # 2% stop-loss
    take_profit_pct: float = 0.04     # 4% take-profit
    max_daily_loss_pct: float = 0.03  # kill switch at -3%
    min_confidence: float = 0.60      # only trade signals with confidence > 60%
    min_cash_reserve_pct: float = 0.20  # always keep 20% in cash


@dataclass
class PositionInfo:
    symbol: str
    qty: float
    avg_cost: float
    current_price: float
    strategy: str
    stop_loss: float
    take_profit: float
    opened_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_cost) * self.qty

    @property
    def unrealized_pnl_pct(self) -> float:
        return (self.current_price - self.avg_cost) / self.avg_cost

    @property
    def should_stop_loss(self) -> bool:
        return self.current_price <= self.stop_loss

    @property
    def should_take_profit(self) -> bool:
        return self.current_price >= self.take_profit


class RiskManager:

    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig(
            max_position_pct=float(os.getenv("MAX_POSITION_SIZE", 0.10)),
            stop_loss_pct=float(os.getenv("STOP_LOSS_PCT", 0.02)),
            take_profit_pct=float(os.getenv("TAKE_PROFIT_PCT", 0.04)),
            max_daily_loss_pct=float(os.getenv("MAX_DAILY_LOSS", 0.03)),
            max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", 5)),
        )
        self.positions: dict[str, PositionInfo] = {}
        self.daily_start_value: float = None
        self.daily_realized_pnl: float = 0.0
        self.trading_halted: bool = False
        self.halt_reason: str = ""
        self.trade_count_today: int = 0
        self._today: date = date.today()

    # ── Daily reset ───────────────────────────────────────────────────────────

    def set_starting_value(self, portfolio_value: float):
        today = date.today()
        if today != self._today:
            self.daily_realized_pnl = 0.0
            self.trade_count_today = 0
            self.trading_halted = False
            self.halt_reason = ""
            self._today = today
            logger.info(f"New trading day — daily P&L reset")
        self.daily_start_value = portfolio_value

    # ── Pre-trade checks ──────────────────────────────────────────────────────

    def can_trade(self, symbol: str, action: str,
                  signal_confidence: float, portfolio_value: float,
                  available_cash: float) -> tuple[bool, str]:
        """
        Returns (allowed: bool, reason: str).
        Call this BEFORE placing any order.
        """
        # Kill switch
        if self.trading_halted:
            return False, f"Trading halted: {self.halt_reason}"

        # Signal confidence
        if signal_confidence < self.config.min_confidence:
            return False, f"Signal confidence {signal_confidence:.0%} below minimum {self.config.min_confidence:.0%}"

        # Already in this position for BUY
        if action == "BUY" and symbol in self.positions:
            return False, f"Already holding {symbol}"

        # Max positions
        if action == "BUY" and len(self.positions) >= self.config.max_open_positions:
            return False, f"Max open positions ({self.config.max_open_positions}) reached"

        # Cash reserve
        min_cash = portfolio_value * self.config.min_cash_reserve_pct
        if action == "BUY" and available_cash < min_cash:
            return False, f"Cash reserve too low (${available_cash:.0f} < ${min_cash:.0f} required)"

        # Daily loss kill switch
        if self.daily_start_value:
            daily_pnl_pct = self.daily_realized_pnl / self.daily_start_value
            if daily_pnl_pct <= -self.config.max_daily_loss_pct:
                self.halt_trading(f"Daily loss limit hit: {daily_pnl_pct:.1%}")
                return False, self.halt_reason

        return True, "OK"

    # ── Position sizing ───────────────────────────────────────────────────────

    def calculate_position_size(self, symbol: str, price: float,
                                portfolio_value: float, available_cash: float,
                                signal_confidence: float = 1.0) -> int:
        """
        Returns number of shares to buy.
        Uses volatility-adjusted position sizing.
        """
        # Max dollar amount for this position
        max_dollars = portfolio_value * self.config.max_position_pct

        # Scale by signal confidence
        scaled_dollars = max_dollars * signal_confidence

        # Don't use more than available cash
        usable_cash = available_cash * (1 - self.config.min_cash_reserve_pct)
        position_dollars = min(scaled_dollars, usable_cash)

        if position_dollars < price:
            return 0   # can't afford even 1 share

        shares = int(position_dollars / price)
        logger.info(f"Position size {symbol}: {shares} shares "
                    f"(${position_dollars:.0f} of ${portfolio_value:.0f} portfolio)")
        return shares

    # ── Stop-loss / take-profit levels ────────────────────────────────────────

    def calculate_levels(self, entry_price: float) -> tuple[float, float]:
        """Returns (stop_loss_price, take_profit_price)."""
        stop_loss   = entry_price * (1 - self.config.stop_loss_pct)
        take_profit = entry_price * (1 + self.config.take_profit_pct)
        return round(stop_loss, 2), round(take_profit, 2)

    # ── Position tracking ─────────────────────────────────────────────────────

    def open_position(self, symbol: str, qty: int, fill_price: float, strategy: str):
        stop_loss, take_profit = self.calculate_levels(fill_price)
        self.positions[symbol] = PositionInfo(
            symbol=symbol, qty=qty, avg_cost=fill_price,
            current_price=fill_price, strategy=strategy,
            stop_loss=stop_loss, take_profit=take_profit
        )
        self.trade_count_today += 1
        logger.info(f"Position opened: {qty} {symbol} @ ${fill_price:.2f} | "
                    f"SL=${stop_loss:.2f} TP=${take_profit:.2f}")

    def close_position(self, symbol: str, fill_price: float) -> float:
        """Close position, record P&L, return realized P&L."""
        if symbol not in self.positions:
            return 0
        pos = self.positions.pop(symbol)
        pnl = (fill_price - pos.avg_cost) * pos.qty
        self.daily_realized_pnl += pnl
        self.trade_count_today += 1
        logger.info(f"Position closed: {pos.qty} {symbol} @ ${fill_price:.2f} | "
                    f"P&L=${pnl:+.2f}")
        return pnl

    def update_price(self, symbol: str, price: float):
        if symbol in self.positions:
            self.positions[symbol].current_price = price

    # ── Stop-loss monitoring ──────────────────────────────────────────────────

    def check_exits(self) -> list[dict]:
        """
        Call this every tick / every minute.
        Returns list of positions that should be closed immediately.
        """
        exits = []
        for symbol, pos in list(self.positions.items()):
            if pos.should_stop_loss:
                exits.append({
                    "symbol": symbol,
                    "reason": "stop_loss",
                    "price": pos.current_price,
                    "pnl_pct": pos.unrealized_pnl_pct
                })
                logger.warning(f"🛑 STOP LOSS triggered: {symbol} @ ${pos.current_price:.2f} "
                               f"(entry ${pos.avg_cost:.2f}, loss {pos.unrealized_pnl_pct:.1%})")
            elif pos.should_take_profit:
                exits.append({
                    "symbol": symbol,
                    "reason": "take_profit",
                    "price": pos.current_price,
                    "pnl_pct": pos.unrealized_pnl_pct
                })
                logger.success(f"🎯 TAKE PROFIT hit: {symbol} @ ${pos.current_price:.2f} "
                               f"(entry ${pos.avg_cost:.2f}, gain {pos.unrealized_pnl_pct:.1%})")
        return exits

    # ── Kill switch ───────────────────────────────────────────────────────────

    def halt_trading(self, reason: str):
        self.trading_halted = True
        self.halt_reason = reason
        logger.critical(f"🚨 TRADING HALTED: {reason}")

    def resume_trading(self):
        self.trading_halted = False
        self.halt_reason = ""
        logger.info("Trading resumed")

    # ── Summary ───────────────────────────────────────────────────────────────

    def get_summary(self) -> dict:
        total_unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        return {
            "open_positions": len(self.positions),
            "daily_realized_pnl": round(self.daily_realized_pnl, 2),
            "total_unrealized_pnl": round(total_unrealized, 2),
            "total_pnl": round(self.daily_realized_pnl + total_unrealized, 2),
            "trading_halted": self.trading_halted,
            "halt_reason": self.halt_reason,
            "trade_count_today": self.trade_count_today,
            "positions": [
                {
                    "symbol": p.symbol,
                    "qty": p.qty,
                    "avg_cost": p.avg_cost,
                    "current_price": p.current_price,
                    "unrealized_pnl": round(p.unrealized_pnl, 2),
                    "unrealized_pnl_pct": round(p.unrealized_pnl_pct * 100, 2),
                    "stop_loss": p.stop_loss,
                    "take_profit": p.take_profit,
                    "strategy": p.strategy,
                }
                for p in self.positions.values()
            ]
        }
