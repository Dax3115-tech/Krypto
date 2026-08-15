"""
strategies/momentum.py
Momentum Strategy: MA Crossover + RSI Filter

Signal logic:
  BUY  when: fast MA crosses above slow MA AND RSI < 65 (not overbought)
  SELL when: fast MA crosses below slow MA OR  RSI > 75 (overbought)

Works best on: trending markets, liquid ETFs (SPY, QQQ)
Timeframe: 1-minute bars, swing timeframe
"""

import pandas as pd
import numpy as np
from loguru import logger


class MomentumStrategy:

    NAME = "momentum_ma_rsi"

    def __init__(self,
                 fast_ma: int = 10,
                 slow_ma: int = 30,
                 rsi_period: int = 14,
                 rsi_overbought: float = 75,
                 rsi_oversold: float = 35):
        self.fast_ma = fast_ma
        self.slow_ma = slow_ma
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self._prev_fast: dict[str, float] = {}
        self._prev_slow: dict[str, float] = {}

    # ── Indicators ─────────────────────────────────────────────────────────────

    def _calc_rsi(self, closes: pd.Series, period: int) -> pd.Series:
        delta = closes.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))

    def _calc_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["fast_ma"] = df["close"].rolling(self.fast_ma).mean()
        df["slow_ma"] = df["close"].rolling(self.slow_ma).mean()
        df["rsi"]     = self._calc_rsi(df["close"], self.rsi_period)
        df["volume_ma"] = df["volume"].rolling(20).mean()
        df["volume_surge"] = df["volume"] > df["volume_ma"] * 1.5
        return df

    # ── Signal generation ──────────────────────────────────────────────────────

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> dict | None:
        """
        Returns a signal dict or None if no trade.
        Signal: { action, price, reason, confidence }
        """
        if len(df) < self.slow_ma + self.rsi_period:
            return None   # not enough data yet

        df = self._calc_indicators(df)
        df.dropna(inplace=True)
        if df.empty:
            return None

        latest   = df.iloc[-1]
        prev     = df.iloc[-2]

        fast_now  = latest["fast_ma"]
        slow_now  = latest["slow_ma"]
        fast_prev = prev["fast_ma"]
        slow_prev = prev["slow_ma"]
        rsi       = latest["rsi"]
        price     = latest["close"]
        vol_surge = latest["volume_surge"]

        # ── BUY signal: golden cross ──────────────────────────────────────────
        if (fast_prev <= slow_prev and        # was below
            fast_now  >  slow_now  and        # crossed above
            rsi < self.rsi_overbought):       # not overbought

            confidence = 0.7
            if vol_surge: confidence += 0.15  # volume confirms
            if rsi < 50:  confidence += 0.10  # room to run
            confidence = min(confidence, 1.0)

            reason = (f"MA crossover UP: fast={fast_now:.2f} > slow={slow_now:.2f}, "
                      f"RSI={rsi:.1f}" + (" | volume surge" if vol_surge else ""))
            logger.info(f"[MOMENTUM] BUY signal {symbol} @ {price:.2f} — {reason}")
            return {"action": "BUY", "price": price,
                    "reason": reason, "confidence": confidence}

        # ── SELL signal: death cross ──────────────────────────────────────────
        if (fast_prev >= slow_prev and        # was above
            fast_now  <  slow_now):           # crossed below

            reason = (f"MA crossover DOWN: fast={fast_now:.2f} < slow={slow_now:.2f}, "
                      f"RSI={rsi:.1f}")
            logger.info(f"[MOMENTUM] SELL signal {symbol} @ {price:.2f} — {reason}")
            return {"action": "SELL", "price": price, "reason": reason, "confidence": 0.8}

        # ── SELL signal: RSI overbought ───────────────────────────────────────
        if rsi > self.rsi_overbought:
            reason = f"RSI overbought: {rsi:.1f} > {self.rsi_overbought}"
            return {"action": "SELL", "price": price, "reason": reason, "confidence": 0.6}

        return None   # hold

    def get_stats(self, df: pd.DataFrame) -> dict:
        """Return current indicator values for the dashboard."""
        if len(df) < self.slow_ma:
            return {}
        df = self._calc_indicators(df)
        df.dropna(inplace=True)
        if df.empty:
            return {}
        latest = df.iloc[-1]
        return {
            "fast_ma": round(latest["fast_ma"], 2),
            "slow_ma": round(latest["slow_ma"], 2),
            "rsi": round(latest["rsi"], 1),
            "volume_surge": bool(latest["volume_surge"]),
        }
