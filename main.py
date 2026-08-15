"""
main.py
Algo Trader — Main Orchestrator

Wires together:
  - Alpaca live data feed (WebSocket)
  - Momentum + Mean Reversion strategies
  - Risk manager (position sizing, stop-loss, kill switch)
  - Alpaca broker (order execution)
  - Flask dashboard (real-time web UI)

Run: python main.py
"""

import os
import time
import signal
import threading
import schedule
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

from data.database import init_db, save_signal, save_trade, save_sd_zone, deactivate_sd_zone
from data.feed import start_feed, price_cache
from strategies.supply_demand import SupplyDemandStrategy
from risk.manager import RiskManager, RiskConfig
from execution.broker import AlpacaBroker
from dashboard.app import init_dashboard, run_dashboard, emit_update, socketio

# ── Config ────────────────────────────────────────────────────────────────────

SYMBOLS = [s.strip() for s in os.getenv("TRADING_SYMBOLS", "SPY,QQQ,AAPL").split(",")]
MIN_BARS_BEFORE_TRADING = 35    # wait for enough history before signaling
STRATEGY_INTERVAL_SECONDS = 60  # run strategies every 60 seconds
LOG_FILE = "logs/algo_trader_{time}.log"

# ── Logging ───────────────────────────────────────────────────────────────────

logger.add(LOG_FILE, rotation="1 day", retention="30 days",
           level=os.getenv("LOG_LEVEL", "INFO"), format="{time} | {level} | {message}")

# ── Global state ──────────────────────────────────────────────────────────────

broker: AlpacaBroker = None
risk_manager: RiskManager = None
strategies = {}
_running = True


# ── Strategy runner ───────────────────────────────────────────────────────────

def run_strategies():
    """Called on a schedule — checks signals for every symbol."""
    if not broker or not risk_manager:
        return

    if not broker.is_market_open():
        logger.debug("Market closed — skipping strategy run")
        return

    if risk_manager.trading_halted:
        logger.warning(f"Trading halted ({risk_manager.halt_reason}) — skipping")
        return

    # Refresh account state
    account = broker.get_account()
    if not account:
        return

    portfolio_value = account.get("portfolio_value", 0)
    cash = account.get("cash", 0)
    risk_manager.set_starting_value(portfolio_value)

    for symbol in SYMBOLS:
        df = price_cache.get_bars_df(symbol, n=100)
        if df.empty or len(df) < MIN_BARS_BEFORE_TRADING:
            logger.debug(f"{symbol}: not enough bars yet ({len(df)}/{MIN_BARS_BEFORE_TRADING})")
            continue

        # Update risk manager with latest price
        price = price_cache.get_price(symbol)
        if price:
            risk_manager.update_price(symbol, price)

        # Run both strategies, use whichever fires first
        for strategy_name, strategy in strategies.items():
            signal = strategy.generate_signal(symbol, df)

            if signal is None:
                continue

            action = signal["action"]
            sig_price = signal["price"]
            confidence = signal["confidence"]
            reason = signal["reason"]

            logger.info(f"Signal: {action} {symbol} via {strategy_name} "
                        f"@ ${sig_price:.2f} (confidence={confidence:.0%})")

            # Save signal to DB
            save_signal(symbol, strategy_name, action, sig_price, reason, confidence)

            # Persist S&D zone to DB if this is a supply/demand signal
            if strategy_name == "supply_demand" and signal:
                zone_top = signal.get("zone_top", sig_price)
                zone_bot = signal.get("zone_bot", sig_price)
                zone_type = "D" if action == "BUY" else "S"
                save_sd_zone(symbol, zone_type, sig_price, zone_top, zone_bot)
                if signal.get("confidence", 0) >= 0.75:   # only deactivate on HIT not NEAR
                    deactivate_sd_zone(symbol, zone_type, sig_price)

            # ── BUY ──────────────────────────────────────────────────────────
            if action == "BUY":
                allowed, reason_blocked = risk_manager.can_trade(
                    symbol, "BUY", confidence, portfolio_value, cash
                )
                if not allowed:
                    logger.info(f"Trade blocked for {symbol}: {reason_blocked}")
                    continue  # try next strategy

                qty = risk_manager.calculate_position_size(
                    symbol, sig_price, portfolio_value, cash, confidence
                )
                if qty == 0:
                    logger.warning(f"Position size 0 for {symbol} — skipping")
                    continue

                # ── S&D specific: use zone bottom as stop loss ────────────────
                # Pine Script logic: if price breaks below demand zone, zone is invalid
                if strategy_name == "supply_demand" and signal.get("zone_bot"):
                    zone_bot = signal["zone_bot"]
                    # Stop loss = just below the zone bottom (0.1% buffer)
                    stop_loss  = round(zone_bot * 0.999, 2)
                    # Take profit = 2× the zone height above entry (risk:reward 1:2)
                    zone_height = sig_price - zone_bot
                    take_profit = round(sig_price + (zone_height * 2), 2)
                    logger.info(f"[S&D] SL=${stop_loss} (zone bot ${zone_bot}) "
                                f"TP=${take_profit} (2× zone height)")
                else:
                    stop_loss, take_profit = risk_manager.calculate_levels(sig_price)
                order = broker.buy_bracket(symbol, qty, stop_loss, take_profit, strategy_name)

                if order:
                    fill_price = broker.wait_for_fill(order["order_id"])
                    if fill_price:
                        risk_manager.open_position(
                            symbol, qty, fill_price, strategy_name,
                            stop_loss=stop_loss, take_profit=take_profit
                        )
                        save_trade(order["order_id"], symbol, "buy", qty,
                                   limit_price=fill_price, strategy=strategy_name)
                        cash -= qty * fill_price
                        break  # ✅ only break on successful fill

            # ── SELL ─────────────────────────────────────────────────────────
            elif action == "SELL":
                if symbol not in risk_manager.positions:
                    continue  # nothing to sell — try next strategy

                allowed, reason_blocked = risk_manager.can_trade(
                    symbol, "SELL", confidence, portfolio_value, cash
                )
                if not allowed:
                    logger.info(f"Sell blocked for {symbol}: {reason_blocked}")
                    continue

                order = broker.sell_all(symbol)
                if order:
                    fill_price = broker.wait_for_fill(order["order_id"])
                    if fill_price:
                        pnl = risk_manager.close_position(symbol, fill_price)
                        save_trade(order["order_id"], symbol, "sell",
                                   order["qty"], limit_price=fill_price,
                                   strategy=strategy_name)
                        break  # ✅ only break on successful sell

    # Push update to dashboard
    emit_update()


def check_stop_losses():
    """Check stop-loss / take-profit on every tick cycle."""
    if not broker or not risk_manager:
        return
    exits = risk_manager.check_exits()
    for exit_signal in exits:
        symbol = exit_signal["symbol"]
        logger.warning(f"Auto-exit {symbol}: {exit_signal['reason']}")
        order = broker.sell_all(symbol)
        if order:
            fill = broker.wait_for_fill(order["order_id"], timeout=15)
            if fill:
                risk_manager.close_position(symbol, fill)
                save_trade(order["order_id"], symbol, "sell",
                           order["qty"], limit_price=fill,
                           strategy=exit_signal["reason"])


def on_tick(symbol: str, price: float, volume: float):
    """Called on every price tick — updates risk manager and checks exits."""
    risk_manager.update_price(symbol, price)
    check_stop_losses()


def end_of_day_cleanup():
    """Close all positions 5 minutes before market close."""
    logger.info("End-of-day cleanup — closing all positions")
    if broker:
        broker.cancel_all_orders()
        broker.liquidate_all()
    if risk_manager:
        for symbol in list(risk_manager.positions.keys()):
            risk_manager.positions.pop(symbol, None)
    logger.info("End-of-day cleanup complete")


# ── Graceful shutdown ─────────────────────────────────────────────────────────

def shutdown(signum, frame):
    global _running
    logger.warning("Shutdown signal received — closing positions and stopping")
    _running = False
    if broker:
        broker.cancel_all_orders()
        broker.liquidate_all()
    exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def main():
    global broker, risk_manager, strategies

    logger.info("=" * 60)
    logger.info("🤖 Algo Trader starting up")
    logger.info(f"   Symbols: {SYMBOLS}")
    logger.info(f"   Mode: {os.getenv('ENV', 'paper').upper()}")
    logger.info("=" * 60)

    # 1. Database
    logger.info("Initializing database...")
    init_db()

    # 2. Broker connection
    logger.info("Connecting to Alpaca...")
    broker = AlpacaBroker()
    account = broker.get_account()
    logger.info(f"Account value: ${account.get('equity', 0):,.2f}")

    # 3. Risk manager
    logger.info("Initializing risk manager...")
    risk_manager = RiskManager()
    risk_manager.set_starting_value(account.get("portfolio_value", 0))

    # 4. Strategies
    logger.info("Loading strategies...")
    strategies = {
        "supply_demand": SupplyDemandStrategy(
            min_pc_change=0.25,
            max_pc_zone=0.6,
            alerts_pc_near=1.5,
            max_zones=100,
        ),
    }
    logger.info(f"Strategies loaded: {list(strategies.keys())}")

    # 5. Live data feed
    logger.info(f"Starting live data feed for {SYMBOLS}...")
    feed = start_feed(SYMBOLS, tick_callbacks=[on_tick])
    logger.info("Feed started — waiting 30s for data to accumulate...")
    time.sleep(30)

    # 6. Dashboard
    logger.info(f"Starting dashboard on port {os.getenv('DASHBOARD_PORT', 5000)}...")
    init_dashboard(risk_manager, broker, price_cache, strategies)
    dashboard_thread = threading.Thread(
        target=run_dashboard,
        kwargs={"host": "0.0.0.0", "port": int(os.getenv("DASHBOARD_PORT", 5000))},
        daemon=True,
        name="Dashboard"
    )
    dashboard_thread.start()

    # 7. Schedule
    schedule.every(STRATEGY_INTERVAL_SECONDS).seconds.do(run_strategies)
    schedule.every().day.at("15:55").do(end_of_day_cleanup)  # 5 min before close

    logger.success("🚀 Algo Trader is LIVE — dashboard at http://localhost:5000")
    logger.info(f"Running strategies every {STRATEGY_INTERVAL_SECONDS}s")

    # Main loop
    while _running:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
