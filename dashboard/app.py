"""
dashboard/app.py
Flask web dashboard with real-time updates.
Shows: portfolio value, open positions, P&L, signals, live prices, trade log.
"""

import os
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from loguru import logger

# These are injected by main.py at startup
_risk_manager = None
_broker = None
_price_cache = None
_strategies = {}

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
socketio = SocketIO(app, cors_allowed_origins="*")


def init_dashboard(risk_manager, broker, price_cache, strategies):
    global _risk_manager, _broker, _price_cache, _strategies
    _risk_manager = risk_manager
    _broker = broker
    _price_cache = price_cache
    _strategies = strategies


def emit_update():
    """Push live data to all connected dashboard clients."""
    try:
        account = _broker.get_account() if _broker else {}
        risk = _risk_manager.get_summary() if _risk_manager else {}

        prices = {}
        if _price_cache:
            for sym in (os.getenv("TRADING_SYMBOLS", "SPY,QQQ").split(",")):
                p = _price_cache.get_price(sym.strip())
                if p:
                    prices[sym.strip()] = round(p, 2)

        socketio.emit("update", {
            "account": account,
            "risk": risk,
            "prices": prices,
            "timestamp": datetime.utcnow().isoformat(),
        })
    except Exception as e:
        logger.error(f"emit_update error: {e}")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("dashboard.html",
                           symbols=os.getenv("TRADING_SYMBOLS", "SPY,QQQ").split(","))


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/account")
def api_account():
    if not _broker:
        return jsonify({"error": "Broker not connected"})
    return jsonify(_broker.get_account())


@app.route("/api/positions")
def api_positions():
    if not _broker:
        return jsonify([])
    return jsonify(_broker.get_positions())


@app.route("/api/risk")
def api_risk():
    if not _risk_manager:
        return jsonify({})
    return jsonify(_risk_manager.get_summary())


@app.route("/api/prices")
def api_prices():
    if not _price_cache:
        return jsonify({})
    symbols = os.getenv("TRADING_SYMBOLS", "SPY,QQQ").split(",")
    prices = {}
    for sym in symbols:
        p = _price_cache.get_price(sym.strip())
        if p:
            prices[sym.strip()] = round(p, 2)
    return jsonify(prices)


@app.route("/api/zones")
def api_zones():
    """Return all active S&D zones for the dashboard zones table."""
    sd = _strategies.get("supply_demand")
    if not sd:
        return jsonify({"demand": [], "supply": []})
    price = None
    if _price_cache:
        symbols = os.getenv("TRADING_SYMBOLS", "SPY").split(",")
        price = _price_cache.get_price(symbols[0].strip())
    zones = sd.get_all_active_zones()
    if price:
        zones["nearby"] = sd.get_nearby_zones(price)
    return jsonify(zones)


@app.route("/api/bars/<symbol>")
def api_bars(symbol):
    if not _price_cache:
        return jsonify([])
    n = int(request.args.get("n", 60))
    df = _price_cache.get_bars_df(symbol.upper(), n=n)
    if df.empty:
        return jsonify([])
    df = df.reset_index()
    df["timestamp"] = df["timestamp"].astype(str)
    return jsonify(df.to_dict("records"))


@app.route("/api/halt", methods=["POST"])
def api_halt():
    """Manual kill switch from dashboard."""
    if _risk_manager:
        _risk_manager.halt_trading("Manual halt via dashboard")
    if _broker:
        _broker.cancel_all_orders()
    return jsonify({"status": "halted"})


@app.route("/api/resume", methods=["POST"])
def api_resume():
    if _risk_manager:
        _risk_manager.resume_trading()
    return jsonify({"status": "resumed"})


@app.route("/api/liquidate", methods=["POST"])
def api_liquidate():
    """Emergency liquidate all — use with caution."""
    if _broker:
        _broker.liquidate_all()
    if _risk_manager:
        _risk_manager.halt_trading("Post-liquidation halt")
    return jsonify({"status": "liquidated"})


@socketio.on("connect")
def on_connect():
    logger.info("Dashboard client connected")
    emit_update()


def run_dashboard(host="0.0.0.0", port=5000, debug=False):
    socketio.run(app, host=host, port=port, debug=debug, use_reloader=False)
