"""
data/feed.py
Alpaca WebSocket live data feed.
- Connects and auto-reconnects
- Loads historical bars on startup (so chart shows history immediately)
- Stores raw ticks to PostgreSQL
- Builds 1-min OHLCV bars in memory
- Runs heartbeat monitor (alerts if feed goes stale)
"""

import os
import json
import time
import threading
from datetime import datetime, timedelta
from collections import defaultdict, deque
import websocket
import pandas as pd
import requests
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

# ── In-memory price + bar storage ─────────────────────────────────────────────

class PriceCache:
    """Thread-safe in-memory cache of recent prices and OHLCV bars."""

    def __init__(self, max_bars: int = 500):
        self.prices: dict[str, float] = {}
        self.bids: dict[str, float] = {}
        self.asks: dict[str, float] = {}
        self.bars: dict[str, deque] = defaultdict(lambda: deque(maxlen=max_bars))
        self._current_bar: dict[str, dict] = {}
        self._current_minute: dict[str, str] = {}
        self.last_tick_time: dict[str, datetime] = {}
        self._lock = threading.Lock()

    # ── Historical bar loader ─────────────────────────────────────────────────

    def load_historical(self, symbol: str, timeframe: str = "1Min",
                        days: int = 5, limit: int = 400):
        """
        Fetch historical OHLCV bars from Alpaca REST API and
        pre-seed the cache so the chart shows history immediately on startup.

        Args:
            symbol:    e.g. 'SPY'
            timeframe: '1Min' | '5Min' | '15Min' | '1Hour' | '1Day'
            days:      how many calendar days of history to fetch
            limit:     max number of bars (Alpaca max = 10,000 per request)
        """
        api_key    = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")
        base_url   = os.getenv("ALPACA_BASE_URL",
                               "https://paper-api.alpaca.markets").replace("/v2", "")

        # Use data API (separate from trading API)
        data_url = "https://data.alpaca.markets/v2"

        start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
        end   = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        url    = f"{data_url}/stocks/{symbol}/bars"
        params = {
            "timeframe": timeframe,
            "start":     start,
            "end":       end,
            "limit":     limit,
            "feed":      "iex",       # free feed — change to 'sip' if you have paid plan
            "adjustment":"raw",
        }
        headers = {
            "APCA-API-KEY-ID":     api_key,
            "APCA-API-SECRET-KEY": secret_key,
        }

        try:
            logger.info(f"Loading {limit} historical {timeframe} bars for {symbol}...")
            resp = requests.get(url, params=params, headers=headers, timeout=15)

            if resp.status_code != 200:
                logger.warning(f"Historical data error {symbol}: {resp.status_code} {resp.text[:200]}")
                return 0

            data = resp.json()
            raw_bars = data.get("bars", [])

            if not raw_bars:
                logger.warning(f"No historical bars returned for {symbol}")
                return 0

            # Handle pagination if Alpaca returns a next_page_token
            next_token = data.get("next_page_token")
            while next_token and len(raw_bars) < limit:
                params["page_token"] = next_token
                resp2 = requests.get(url, params=params, headers=headers, timeout=15)
                if resp2.status_code == 200:
                    d2 = resp2.json()
                    raw_bars.extend(d2.get("bars", []))
                    next_token = d2.get("next_page_token")
                else:
                    break

            # Pre-seed the cache
            with self._lock:
                for bar in raw_bars:
                    ts = bar["t"][:16].replace("T", " ")   # "2024-01-15T09:30:00Z" → "2024-01-15 09:30"
                    self.bars[symbol].append({
                        "timestamp": ts,
                        "open":   float(bar["o"]),
                        "high":   float(bar["h"]),
                        "low":    float(bar["l"]),
                        "close":  float(bar["c"]),
                        "volume": float(bar["v"]),
                    })
                # Set latest price from last bar
                if raw_bars:
                    self.prices[symbol] = float(raw_bars[-1]["c"])

            logger.success(f"Loaded {len(raw_bars)} historical bars for {symbol} "
                           f"({timeframe}, last {days} days)")
            return len(raw_bars)

        except Exception as e:
            logger.error(f"load_historical error for {symbol}: {e}")
            return 0

    def load_historical_all(self, symbols: list[str], timeframe: str = "1Min",
                             days: int = 5, limit: int = 400):
        """Load historical bars for all symbols on startup."""
        for symbol in symbols:
            self.load_historical(symbol, timeframe=timeframe, days=days, limit=limit)
            time.sleep(0.3)   # small delay to avoid rate limiting

    # ── Live price updates ────────────────────────────────────────────────────

    def update_price(self, symbol: str, price: float, volume: float = 0,
                     bid: float = None, ask: float = None):
        with self._lock:
            self.prices[symbol] = price
            self.last_tick_time[symbol] = datetime.utcnow()
            if bid: self.bids[symbol] = bid
            if ask: self.asks[symbol] = ask
            self._update_bar(symbol, price, volume)

    def _update_bar(self, symbol: str, price: float, volume: float):
        """Aggregate ticks into 1-minute OHLCV bars."""
        minute = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        if self._current_minute.get(symbol) != minute:
            if symbol in self._current_bar:
                self.bars[symbol].append(dict(self._current_bar[symbol]))
            self._current_bar[symbol] = {
                "timestamp": minute,
                "open": price, "high": price,
                "low": price, "close": price,
                "volume": volume
            }
            self._current_minute[symbol] = minute
        else:
            bar = self._current_bar[symbol]
            bar["high"]   = max(bar["high"], price)
            bar["low"]    = min(bar["low"], price)
            bar["close"]  = price
            bar["volume"] += volume

    def get_price(self, symbol: str) -> float | None:
        return self.prices.get(symbol)

    def get_bars_df(self, symbol: str, n: int = 100) -> pd.DataFrame:
        with self._lock:
            bars = list(self.bars[symbol])[-n:]
        if not bars:
            return pd.DataFrame()
        df = pd.DataFrame(bars)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index("timestamp", inplace=True)
        return df

    def is_stale(self, symbol: str, threshold_seconds: int = 60) -> bool:
        last = self.last_tick_time.get(symbol)
        if not last:
            return True
        return (datetime.utcnow() - last).total_seconds() > threshold_seconds

    def get_spread(self, symbol: str) -> float | None:
        bid = self.bids.get(symbol)
        ask = self.asks.get(symbol)
        if bid and ask:
            return ask - bid
        return None


# Global cache — shared across the app
price_cache = PriceCache()


# ── WebSocket Feed ─────────────────────────────────────────────────────────────

class AlpacaFeed:
    """
    Alpaca WebSocket data feed.
    Subscribes to trades + quotes for configured symbols.
    Auto-reconnects on disconnect.
    """

    WS_URL = "wss://stream.data.alpaca.markets/v2/iex"  # free IEX feed
    # WS_URL = "wss://stream.data.alpaca.markets/v2/sip"  # paid SIP feed

    def __init__(self, symbols: list[str], on_signal_callback=None):
        self.symbols = [s.upper() for s in symbols]
        self.on_signal_callback = on_signal_callback
        self.api_key = os.getenv("ALPACA_API_KEY")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY")
        self.ws = None
        self.connected = False
        self.reconnect_delay = 5
        self._stop = False
        self._tick_callbacks: list = []

    def add_tick_callback(self, fn):
        """Register a function to call on every price update."""
        self._tick_callbacks.append(fn)

    def _on_open(self, ws):
        logger.info("WebSocket connected — authenticating...")
        auth = {"action": "auth", "key": self.api_key, "secret": self.secret_key}
        ws.send(json.dumps(auth))

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            if isinstance(data, list):
                for msg in data:
                    self._handle_message(msg)
            else:
                self._handle_message(data)
        except Exception as e:
            logger.error(f"WebSocket message error: {e}")

    def _handle_message(self, msg):
        t = msg.get("T")

        if t == "success" and msg.get("msg") == "authenticated":
            logger.success("Authenticated — subscribing to symbols...")
            sub = {
                "action": "subscribe",
                "trades": self.symbols,
                "quotes": self.symbols,
            }
            self.ws.send(json.dumps(sub))
            self.connected = True

        elif t == "t":   # trade tick
            symbol = msg.get("S")
            price  = float(msg.get("p", 0))
            volume = float(msg.get("s", 0))

            if price > 0:
                price_cache.update_price(symbol, price, volume)
                for cb in self._tick_callbacks:
                    try:
                        cb(symbol, price, volume)
                    except Exception as e:
                        logger.error(f"Tick callback error: {e}")

        elif t == "q":   # quote update
            symbol = msg.get("S")
            bid    = float(msg.get("bp", 0) or 0)
            ask    = float(msg.get("ap", 0) or 0)
            if bid and ask:
                price_cache.update_price(symbol, (bid + ask) / 2, bid=bid, ask=ask)

        elif t == "error":
            logger.error(f"Feed error: {msg}")

    def _on_error(self, ws, error):
        logger.error(f"WebSocket error: {error}")
        self.connected = False

    def _on_close(self, ws, close_status, close_msg):
        logger.warning(f"WebSocket closed: {close_status} {close_msg}")
        self.connected = False

    def _heartbeat_monitor(self):
        """Alert if any symbol's feed goes stale."""
        while not self._stop:
            time.sleep(30)
            for symbol in self.symbols:
                if price_cache.is_stale(symbol, threshold_seconds=120):
                    logger.warning(f"⚠️  Feed may be stale for {symbol} — no tick in 2+ minutes")

    def start(self):
        """Start the feed in a background thread with auto-reconnect."""
        threading.Thread(target=self._heartbeat_monitor, daemon=True).start()

        while not self._stop:
            try:
                logger.info(f"Connecting to Alpaca feed for: {self.symbols}")
                self.ws = websocket.WebSocketApp(
                    self.WS_URL,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self.ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                logger.error(f"Feed crashed: {e}")

            if not self._stop:
                logger.info(f"Reconnecting in {self.reconnect_delay}s...")
                time.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, 60)

    def stop(self):
        self._stop = True
        if self.ws:
            self.ws.close()


def start_feed(symbols: list[str], tick_callbacks: list = None) -> AlpacaFeed:
    """Start the live feed in a daemon thread. Returns the feed instance."""
    feed = AlpacaFeed(symbols)
    if tick_callbacks:
        for cb in tick_callbacks:
            feed.add_tick_callback(cb)
    thread = threading.Thread(target=feed.start, daemon=True, name="AlpacaFeed")
    thread.start()
    return feed
