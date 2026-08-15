"""
strategies/supply_demand.py
Supply & Demand Zone Strategy
Converted from Pine Script: Supply & Demand Zones [BacktestBot] v1.1

What this does:
  - Detects demand zones (price likely to bounce UP from)
  - Detects supply zones  (price likely to reverse DOWN from)
  - Tracks active vs hit zones
  - Generates BUY signal when price hits/approaches a demand zone
  - Generates SELL signal when price hits/approaches a supply zone
  - Stores all zones to PostgreSQL for persistence + dashboard display

Pine Script → Python mapping:
  bear_run / bull_run     → count consecutive bearish/bullish candles
  s1_level                → base price of the zone (open of first candle in run)
  add_ds_zone()           → SupplyDemandStrategy.detect_zones()
  check_ds_zone_hit()     → SupplyDemandStrategy.check_zone_hits()
  draw_nearby_ds_s1()     → SupplyDemandStrategy.get_nearby_zones()
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger
from typing import Literal


# ── Zone data structures ──────────────────────────────────────────────────────

@dataclass
class Zone:
    zone_type: Literal["D", "S"]    # D=Demand, S=Supply
    s1: float                        # key price level (top of demand / bottom of supply)
    top: float                       # upper boundary
    bot: float                       # lower boundary
    formed_at: datetime              # when the zone was created
    formed_index: int                # bar index when zone was created
    active: bool = True              # False once price hits it
    hit_count: int = 0               # how many times price touched it

    @property
    def midpoint(self) -> float:
        return (self.top + self.bot) / 2

    @property
    def height_pct(self) -> float:
        return abs(self.top - self.bot) / self.bot * 100

    def to_dict(self) -> dict:
        return {
            "zone_type": self.zone_type,
            "s1": round(self.s1, 4),
            "top": round(self.top, 4),
            "bot": round(self.bot, 4),
            "formed_at": self.formed_at.isoformat(),
            "active": self.active,
            "hit_count": self.hit_count,
            "height_pct": round(self.height_pct, 3),
        }


# ── Core strategy ─────────────────────────────────────────────────────────────

class SupplyDemandStrategy:

    NAME = "supply_demand_zones"

    def __init__(
        self,
        min_pc_change: float = 0.25,      # Pine: ds_min_pc_change
        max_pc_zone: float = 0.6,          # Pine: ds_max_pc_zone
        line_pc_display: float = 3.0,      # Pine: ds_line_pc_display
        alerts_pc_near: float = 1.5,       # Pine: ds_alerts_pc_near
        max_zones: int = 100,              # Pine: ds_max_zones
    ):
        self.min_pc_change = min_pc_change
        self.max_pc_zone = max_pc_zone
        self.line_pc_display = line_pc_display
        self.alerts_pc_near = alerts_pc_near
        self.max_zones = max_zones

        # Active zone stores (mirrors Pine Script arrays)
        self.demand_zones: list[Zone] = []
        self.supply_zones: list[Zone] = []

        # Track which zone timestamps we've already added (dedup)
        self._demand_times_seen: set = set()
        self._supply_times_seen: set = set()

    # ── Utility functions (converted from Pine Script) ────────────────────────

    def _pc_diff_abs(self, x_start: float, y_end: float) -> float:
        """Pine: get_pc_diff_abs — absolute % difference between two prices."""
        if x_start == 0:
            return 0
        return abs((y_end - x_start) / x_start * 100)

    def _amount_by_pc(self, amount: float, pc: float, direction: str) -> float:
        """Pine: get_amount_by_pc — adjust a price by a percentage."""
        pc_amount = amount * (pc / 100)
        return amount + pc_amount if direction == "add" else amount - pc_amount

    def _count_run(self, df: pd.DataFrame, direction: str) -> pd.Series:
        """
        Pine: bear_run / bull_run
        Count consecutive bearish (direction='bear') or bullish ('bull') candles.
        Returns a Series where each value = bars since the run started.
        """
        if direction == "bull":
            is_candle = df["open"] > df["close"]   # bullish = close > open
        else:
            is_candle = df["open"] < df["close"]   # bearish = close < open

        # Count how many bars since last opposite candle
        run = pd.Series(0, index=df.index)
        count = 0
        for i in range(len(df)):
            if is_candle.iloc[i]:
                count = 0
            else:
                count += 1
            run.iloc[i] = count
        return run

    # ── Zone detection (converted from add_ds_zone) ───────────────────────────

    def detect_zones(self, df: pd.DataFrame, symbol: str) -> tuple[list[Zone], list[Zone]]:
        """
        Main zone detection — equivalent to add_ds_zone() in Pine Script.
        Scans all bars in df and returns (demand_zones, supply_zones).
        Call this on startup with historical data, then incrementally.
        """
        if len(df) < 5:
            return self.demand_zones, self.supply_zones

        opens  = df["open"].values
        closes = df["close"].values
        highs  = df["high"].values
        lows   = df["low"].values
        times  = df.index.tolist()

        # ── Pine: bull_run / bear_run ─────────────────────────────────────────
        # bull_run[i] = bars since open < close (bearish candle interrupted bull run)
        # In Python we iterate forward; Pine looks back
        for i in range(2, len(df)):
            o, c = opens[i], closes[i]
            o1, c1 = opens[i-1], closes[i-1]
            o2, c2 = opens[i-2], closes[i-2]
            ts = times[i-1]         # s1_time = time[1] in Pine (one bar behind)

            # ── Bull run detection → Demand zone ────────────────────────────
            # Pine: bull_run == 1 means this bar completed a bullish run
            # A bull run ends when a bearish candle appears after ≥1 bullish
            bull_run = self._get_run_length(opens, closes, i, "bull")
            bear_run = self._get_run_length(opens, closes, i, "bear")

            # ── s1_level logic (Pine lines 90-100) ──────────────────────────
            # Doji case: prev candle is nearly flat and one before is opposite
            is_doji = self._pc_diff_abs(o1, c1) < 0.02

            s1_level_demand = None
            s1_level_supply = None

            if bull_run >= 1:
                # Demand zone: price ran up, s1 is where it started
                s1_idx = i - bull_run          # bar where bull run began
                s1_level_demand = opens[s1_idx] if not is_doji else opens[i-2]
                bars_to_s1 = bull_run

                pc_change = self._pc_diff_abs(closes[i], opens[i - bars_to_s1 + 1]) if bars_to_s1 >= 1 else 0
                ts_key = str(ts)

                if pc_change >= self.min_pc_change and ts_key not in self._demand_times_seen:
                    zone = self._build_zone("D", df, i, bull_run, s1_level_demand, ts)
                    if zone:
                        self.demand_zones.insert(0, zone)
                        self._demand_times_seen.add(ts_key)
                        self._trim_zones("D")
                        logger.debug(f"[S&D] Demand zone added for {symbol}: "
                                     f"${zone.bot:.2f}–${zone.top:.2f}")

            if bear_run >= 1:
                # Supply zone: price ran down, s1 is where it started
                s1_idx = i - bear_run
                s1_level_supply = opens[s1_idx] if not is_doji else opens[i-2]
                bars_to_s1 = bear_run

                pc_change = self._pc_diff_abs(closes[i], opens[i - bars_to_s1 + 1]) if bars_to_s1 >= 1 else 0
                ts_key = str(ts)

                if pc_change >= self.min_pc_change and ts_key not in self._supply_times_seen:
                    zone = self._build_zone("S", df, i, bear_run, s1_level_supply, ts)
                    if zone:
                        self.supply_zones.insert(0, zone)
                        self._supply_times_seen.add(ts_key)
                        self._trim_zones("S")
                        logger.debug(f"[S&D] Supply zone added for {symbol}: "
                                     f"${zone.bot:.2f}–${zone.top:.2f}")

        return self.demand_zones, self.supply_zones

    def _get_run_length(self, opens, closes, current_idx, direction) -> int:
        """Count how many consecutive bull/bear candles ending at current_idx - 1."""
        count = 0
        for j in range(current_idx - 1, -1, -1):
            if direction == "bull" and closes[j] > opens[j]:
                count += 1
            elif direction == "bear" and closes[j] < opens[j]:
                count += 1
            else:
                break
        return count

    def _build_zone(self, zone_type: str, df: pd.DataFrame,
                    i: int, bars_to_s1: int, s1_level: float, ts) -> Zone | None:
        """
        Build a Zone object from bar data.
        Equivalent to the top/bot calculation in add_ds_zone() Pine Script.
        """
        opens  = df["open"].values
        closes = df["close"].values
        highs  = df["high"].values
        lows   = df["low"].values

        if bars_to_s1 < 1 or i - bars_to_s1 < 0:
            return None

        s1_idx = max(i - bars_to_s1, 0)

        if zone_type == "S":
            # Supply: top is the high of the run start, bot is s1_level
            top = max(highs[s1_idx], highs[min(s1_idx + 1, len(highs)-1)])
            bot = s1_level
        else:
            # Demand: top is s1_level, bot is the low of the run start
            top = s1_level
            bot = min(lows[s1_idx], lows[min(s1_idx + 1, len(lows)-1)])

        # ── Pine: adjust zone if it's too big ────────────────────────────────
        top_bot_pc_diff = self._pc_diff_abs(top, bot)
        candle_before_pc = self._pc_diff_abs(opens[s1_idx], closes[s1_idx])

        if zone_type == "S" and top_bot_pc_diff > self.max_pc_zone:
            if candle_before_pc <= self.max_pc_zone:
                bot = s1_level
            else:
                bot = self._amount_by_pc(closes[s1_idx], self.max_pc_zone / 5, "minus")
            top = self._amount_by_pc(bot, self.max_pc_zone, "add")

        elif zone_type == "D" and top_bot_pc_diff > self.max_pc_zone:
            if candle_before_pc <= self.max_pc_zone:
                top = s1_level
            else:
                top = self._amount_by_pc(closes[s1_idx], self.max_pc_zone / 5, "add")
            bot = self._amount_by_pc(top, self.max_pc_zone, "minus")

        top = round(top, 6)
        bot = round(bot, 6)
        s1  = bot if zone_type == "S" else top   # Pine: _s1 = _bot for S, _top for D

        formed_at = ts if isinstance(ts, datetime) else datetime.utcnow()

        return Zone(
            zone_type=zone_type,
            s1=s1,
            top=top,
            bot=bot,
            formed_at=formed_at,
            formed_index=i,
        )

    def _trim_zones(self, zone_type: str):
        """
        Pine: trim inactive zones when over max_zones.
        Remove oldest inactive zones first.
        """
        zones = self.demand_zones if zone_type == "D" else self.supply_zones
        if len(zones) > self.max_zones:
            # Remove inactive from the end first
            inactive = [z for z in zones if not z.active]
            for z in reversed(inactive):
                zones.remove(z)
                if len(zones) <= self.max_zones:
                    break

    # ── Zone hit detection (converted from check_ds_zone_hit) ─────────────────

    def check_zone_hits(self, current_high: float, current_low: float,
                        current_price: float) -> list[dict]:
        """
        Pine: check_ds_zone_hit()
        Check if price has hit or is near any active zone.
        Returns list of signal dicts for the trading engine.
        """
        signals = []

        # ── Demand zones (buy signal) ─────────────────────────────────────────
        for zone in list(self.demand_zones):
            if not zone.active:
                continue

            price_near = self._amount_by_pc(zone.s1, self.alerts_pc_near, "add")

            if current_low <= zone.s1:
                # HIT — price entered the demand zone
                zone.active = False
                zone.hit_count += 1
                signals.append({
                    "action": "BUY",
                    "zone_type": "D",
                    "alert_type": "H",   # Hit
                    "s1": zone.s1,
                    "top": zone.top,
                    "bot": zone.bot,
                    "price": current_price,
                    "reason": f"Demand zone HIT @ ${zone.s1:.4f} (zone ${zone.bot:.4f}–${zone.top:.4f})",
                    "confidence": 0.75,
                })
                logger.info(f"[S&D] 🟢 DEMAND ZONE HIT @ ${zone.s1:.4f}")

            elif current_low <= price_near:
                # NEAR — price approaching demand zone
                signals.append({
                    "action": "BUY",
                    "zone_type": "D",
                    "alert_type": "N",   # Near
                    "s1": zone.s1,
                    "top": zone.top,
                    "bot": zone.bot,
                    "price": current_price,
                    "reason": f"Approaching demand zone @ ${zone.s1:.4f} (within {self.alerts_pc_near}%)",
                    "confidence": 0.55,
                })
                logger.debug(f"[S&D] Demand zone approaching @ ${zone.s1:.4f}")

            # Pine: loop_break_pc = 5 — stop checking if price is too far away
            elif current_low > zone.s1 and self._pc_diff_abs(current_low, zone.s1) > 5:
                break

        # ── Supply zones (sell signal) ────────────────────────────────────────
        for zone in list(self.supply_zones):
            if not zone.active:
                continue

            price_near = self._amount_by_pc(zone.s1, self.alerts_pc_near, "minus")

            if current_high >= zone.s1:
                # HIT — price entered supply zone
                zone.active = False
                zone.hit_count += 1
                signals.append({
                    "action": "SELL",
                    "zone_type": "S",
                    "alert_type": "H",
                    "s1": zone.s1,
                    "top": zone.top,
                    "bot": zone.bot,
                    "price": current_price,
                    "reason": f"Supply zone HIT @ ${zone.s1:.4f} (zone ${zone.bot:.4f}–${zone.top:.4f})",
                    "confidence": 0.75,
                })
                logger.info(f"[S&D] 🔴 SUPPLY ZONE HIT @ ${zone.s1:.4f}")

            elif current_high >= price_near:
                signals.append({
                    "action": "SELL",
                    "zone_type": "S",
                    "alert_type": "N",
                    "s1": zone.s1,
                    "top": zone.top,
                    "bot": zone.bot,
                    "price": current_price,
                    "reason": f"Approaching supply zone @ ${zone.s1:.4f} (within {self.alerts_pc_near}%)",
                    "confidence": 0.55,
                })
                logger.debug(f"[S&D] Supply zone approaching @ ${zone.s1:.4f}")

            elif current_high < zone.s1 and self._pc_diff_abs(current_high, zone.s1) > 5:
                break

        return signals

    # ── generate_signal — same interface as momentum.py / mean_reversion.py ───

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> dict | None:
        """
        Called by main.py trading loop every 60 seconds.
        Detects new zones from latest bars and checks for hits.
        Returns first actionable signal or None.
        """
        if len(df) < 10:
            return None

        # Run zone detection on latest bars (incremental — only last 50 bars)
        recent = df.tail(50).copy()
        self.detect_zones(recent, symbol)

        # Check current bar for zone hits
        latest = df.iloc[-1]
        current_high  = latest["high"]
        current_low   = latest["low"]
        current_price = latest["close"]

        signals = self.check_zone_hits(current_high, current_low, current_price)

        if not signals:
            return None

        # Prioritise HIT over NEAR, then highest confidence
        signals.sort(key=lambda s: (s["alert_type"] == "H", s["confidence"]), reverse=True)
        best = signals[0]

        return {
            "action": best["action"],
            "price": best["price"],
            "reason": best["reason"],
            "confidence": best["confidence"],
            "zone_top": best["top"],
            "zone_bot": best["bot"],
        }

    # ── Nearby zones (for dashboard display) ─────────────────────────────────

    def get_nearby_zones(self, current_price: float) -> dict:
        """
        Pine: draw_nearby_ds_s1()
        Returns active zones within line_pc_display% of current price.
        Used by the dashboard to show relevant zones.
        """
        nearby_demand = []
        nearby_supply = []

        for zone in self.demand_zones:
            if zone.active and self._pc_diff_abs(current_price, zone.s1) <= self.line_pc_display:
                nearby_demand.append(zone.to_dict())

        for zone in self.supply_zones:
            if zone.active and self._pc_diff_abs(current_price, zone.s1) <= self.line_pc_display:
                nearby_supply.append(zone.to_dict())

        return {
            "demand": nearby_demand[:5],   # max 5 to show
            "supply": nearby_supply[:5],
        }

    def get_all_active_zones(self) -> dict:
        """Return all active zones for the dashboard zones table."""
        return {
            "demand": [z.to_dict() for z in self.demand_zones if z.active],
            "supply": [z.to_dict() for z in self.supply_zones if z.active],
            "demand_total": len(self.demand_zones),
            "supply_total": len(self.supply_zones),
            "demand_active": sum(1 for z in self.demand_zones if z.active),
            "supply_active": sum(1 for z in self.supply_zones if z.active),
        }

    def get_stats(self, df: pd.DataFrame) -> dict:
        """Return zone stats for the dashboard indicator panel."""
        if df.empty:
            return {}
        price = df.iloc[-1]["close"]
        nearby = self.get_nearby_zones(price)
        return {
            "active_demand_zones": sum(1 for z in self.demand_zones if z.active),
            "active_supply_zones": sum(1 for z in self.supply_zones if z.active),
            "nearby_demand": len(nearby["demand"]),
            "nearby_supply": len(nearby["supply"]),
            "nearest_demand": nearby["demand"][0]["s1"] if nearby["demand"] else None,
            "nearest_supply": nearby["supply"][0]["s1"] if nearby["supply"] else None,
        }
