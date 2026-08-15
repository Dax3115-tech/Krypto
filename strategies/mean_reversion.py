"""
strategies/mean_reversion.py
Mean Reversion Strategy: Bollinger Bands + RSI

Signal logic:
  BUY  when: price touches/breaks lower Bollinger Band AND RSI < 30 (oversold)
  SELL when: price touches/breaks upper Bollinger Band OR  RSI > 70 (overbought)

Works best on: range-bound markets, stable large-cap stocks
Timeframe: 1-minute bars
"""

import pandas as pd
import numpy as np
from loguru import logger


class MeanReversionStrategy:

    NAME = "mean_reversion_bb_rsi"

    def __init__(self,
                 bb_period: int = 20,
                 bb_std: float = 2.0,
                 rsi_period: int = 14,
                 rsi_oversold: float = 30,
                 rsi_overbought: float = 70):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

    # ── Indicators ─────────────────────────────────────────────────────────────

    def _calc_bollinger(self, closes: pd.Series) -> tuple:
        mid   = closes.rolling(self.bb_period).mean()
        std   = closes.rolling(self.bb_period).std()
        upper = mid + self.bb_std * std
        lower = mid - self.bb_std * std
        return upper, mid, lower

    def _calc_rsi(self, closes: pd.Series) -> pd.Series:
        delta = closes.diff()
        gain  = delta.clip(lower=0).rolling(self.rsi_period).mean()
        loss  = (-delta.clip(upper=0)).rolling(self.rsi_period).mean()
        rs    = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))

    def _calc_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = self._calc_rsi(df["close"])
        df["bb_upper"], df["bb_mid"], df["bb_lower"] = self._calc_bollinger(df["close"])
        df["bb_pct"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"] + 1e-10)
        # Price momentum (3-bar)
        df["momentum"] = df["close"].pct_change(3)
        return df

    # ── Signal generation ──────────────────────────────────────────────────────

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> dict | None:
        min_bars = max(self.bb_period, self.rsi_period) + 5
        if len(df) < min_bars:
            return None

        df = self._calc_indicators(df)
        df.dropna(inplace=True)
        if df.empty:
            return None

        latest = df.iloc[-1]
        price  = latest["close"]
        rsi    = latest["rsi"]
        bb_pct = latest["bb_pct"]         # 0=lower band, 1=upper band

        # ── BUY: oversold bounce ──────────────────────────────────────────────
        if (price <= latest["bb_lower"] * 1.002 and   # at or below lower band
            rsi < self.rsi_oversold):                  # RSI confirms oversold

            confidence = 0.65
            if bb_pct < -0.05: confidence += 0.15     # well below band
            if rsi < 25:       confidence += 0.10     # deeply oversold
            confidence = min(confidence, 1.0)

            reason = (f"Oversold bounce: price={price:.2f} at lower BB={latest['bb_lower']:.2f}, "
                      f"RSI={rsi:.1f}")
            logger.info(f"[MEAN REV] BUY signal {symbol} @ {price:.2f} — {reason}")
            return {"action": "BUY", "price": price,
                    "reason": reason, "confidence": confidence}

        # ── SELL: overbought reversal ─────────────────────────────────────────
        if (price >= latest["bb_upper"] * 0.998 and   # at or above upper band
            rsi > self.rsi_overbought):                # RSI confirms overbought

            reason = (f"Overbought reversal: price={price:.2f} at upper BB={latest['bb_upper']:.2f}, "
                      f"RSI={rsi:.1f}")
            logger.info(f"[MEAN REV] SELL signal {symbol} @ {price:.2f} — {reason}")
            return {"action": "SELL", "price": price, "reason": reason, "confidence": 0.75}

        return None

    def get_stats(self, df: pd.DataFrame) -> dict:
        """Return current indicator values for the dashboard."""
        if len(df) < self.bb_period:
            return {}
        df = self._calc_indicators(df)
        df.dropna(inplace=True)
        if df.empty:
            return {}
        latest = df.iloc[-1]
        return {
            "rsi": round(latest["rsi"], 1),
            "bb_upper": round(latest["bb_upper"], 2),
            "bb_mid": round(latest["bb_mid"], 2),
            "bb_lower": round(latest["bb_lower"], 2),
            "bb_pct": round(latest["bb_pct"], 3),
        }
