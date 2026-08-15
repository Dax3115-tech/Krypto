"""
data/database.py
PostgreSQL schema + connection for the algo trader.
Tables: ticks, trades, positions, daily_pnl, signals
"""

import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, Float, String,
    DateTime, Boolean, Text, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker
from loguru import logger

Base = declarative_base()


# ── Models ────────────────────────────────────────────────────────────────────

class Tick(Base):
    """Raw price ticks from WebSocket feed."""
    __tablename__ = "ticks"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    symbol    = Column(String(10), nullable=False)
    price     = Column(Float, nullable=False)
    volume    = Column(Float, default=0)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    bid       = Column(Float)
    ask       = Column(Float)

    __table_args__ = (
        Index("ix_ticks_symbol_ts", "symbol", "timestamp"),
    )


class OHLCV(Base):
    """1-minute OHLCV bars built from ticks."""
    __tablename__ = "ohlcv"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    symbol    = Column(String(10), nullable=False)
    open      = Column(Float)
    high      = Column(Float)
    low       = Column(Float)
    close     = Column(Float)
    volume    = Column(Float)
    timestamp = Column(DateTime, nullable=False)
    timeframe = Column(String(5), default="1min")

    __table_args__ = (
        Index("ix_ohlcv_symbol_ts", "symbol", "timestamp"),
    )


class Signal(Base):
    """Strategy signals (buy/sell/hold) with metadata."""
    __tablename__ = "signals"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    symbol     = Column(String(10), nullable=False)
    strategy   = Column(String(50), nullable=False)
    action     = Column(String(10), nullable=False)   # BUY | SELL | HOLD
    price      = Column(Float)
    confidence = Column(Float, default=1.0)           # 0–1
    reason     = Column(Text)
    timestamp  = Column(DateTime, default=datetime.utcnow)
    acted_on   = Column(Boolean, default=False)


class Trade(Base):
    """Every order placed, filled, or cancelled."""
    __tablename__ = "trades"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    order_id      = Column(String(50), unique=True)
    symbol        = Column(String(10), nullable=False)
    side          = Column(String(5), nullable=False)   # buy | sell
    qty           = Column(Float, nullable=False)
    filled_price  = Column(Float)
    limit_price   = Column(Float)
    status        = Column(String(20), default="pending")
    strategy      = Column(String(50))
    pnl           = Column(Float, default=0)
    commission    = Column(Float, default=0)
    created_at    = Column(DateTime, default=datetime.utcnow)
    filled_at     = Column(DateTime)


class Position(Base):
    """Current open positions."""
    __tablename__ = "positions"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    symbol       = Column(String(10), unique=True, nullable=False)
    qty          = Column(Float, nullable=False)
    avg_cost     = Column(Float, nullable=False)
    current_price= Column(Float)
    unrealized_pnl = Column(Float, default=0)
    strategy     = Column(String(50))
    stop_loss    = Column(Float)
    take_profit  = Column(Float)
    opened_at    = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow)


class DailyPnL(Base):
    """Daily P&L snapshot for the dashboard charts."""
    __tablename__ = "daily_pnl"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    date          = Column(DateTime, nullable=False, unique=True)
    starting_cash = Column(Float)
    ending_cash   = Column(Float)
    realized_pnl  = Column(Float, default=0)
    unrealized_pnl= Column(Float, default=0)
    total_pnl     = Column(Float, default=0)
    total_trades  = Column(Integer, default=0)
    win_trades    = Column(Integer, default=0)
    portfolio_value = Column(Float)


# ── Connection ────────────────────────────────────────────────────────────────

_engine = None
_Session = None


def get_engine():
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/algotrader")
        _engine = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)
    return _engine


def get_session():
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine())
    return _Session()


def init_db():
    """Create all tables if they don't exist."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("Database tables created / verified")


def save_tick(symbol: str, price: float, volume: float = 0, bid: float = None, ask: float = None):
    session = get_session()
    try:
        tick = Tick(symbol=symbol, price=price, volume=volume, bid=bid, ask=ask)
        session.add(tick)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"save_tick error: {e}")
    finally:
        session.close()


def save_signal(symbol, strategy, action, price, reason="", confidence=1.0):
    session = get_session()
    try:
        sig = Signal(symbol=symbol, strategy=strategy, action=action,
                     price=price, reason=reason, confidence=confidence)
        session.add(sig)
        session.commit()
        return sig.id
    except Exception as e:
        session.rollback()
        logger.error(f"save_signal error: {e}")
    finally:
        session.close()


def save_trade(order_id, symbol, side, qty, limit_price=None, strategy=None):
    session = get_session()
    try:
        trade = Trade(order_id=order_id, symbol=symbol, side=side,
                      qty=qty, limit_price=limit_price, strategy=strategy)
        session.add(trade)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"save_trade error: {e}")
    finally:
        session.close()


def get_recent_ohlcv(symbol: str, limit: int = 100) -> list:
    session = get_session()
    try:
        rows = (session.query(OHLCV)
                .filter(OHLCV.symbol == symbol)
                .order_by(OHLCV.timestamp.desc())
                .limit(limit)
                .all())
        return list(reversed(rows))
    finally:
        session.close()


class SupplyDemandZone(Base):
    """Persisted supply & demand zones."""
    __tablename__ = "sd_zones"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    symbol      = Column(String(10), nullable=False)
    zone_type   = Column(String(1), nullable=False)   # D | S
    s1          = Column(Float, nullable=False)        # key level
    top         = Column(Float, nullable=False)
    bot         = Column(Float, nullable=False)
    active      = Column(Boolean, default=True)
    hit_count   = Column(Integer, default=0)
    formed_at   = Column(DateTime)
    updated_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_sd_zones_symbol_type", "symbol", "zone_type"),
    )


def save_sd_zone(symbol: str, zone_type: str, s1: float,
                 top: float, bot: float, formed_at=None):
    session = get_session()
    try:
        # Skip if already exists (same symbol + s1 + type)
        existing = session.query(SupplyDemandZone).filter_by(
            symbol=symbol, zone_type=zone_type, s1=s1
        ).first()
        if existing:
            return
        zone = SupplyDemandZone(
            symbol=symbol, zone_type=zone_type, s1=s1,
            top=top, bot=bot, formed_at=formed_at or datetime.utcnow()
        )
        session.add(zone)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"save_sd_zone error: {e}")
    finally:
        session.close()


def get_active_sd_zones(symbol: str) -> list:
    session = get_session()
    try:
        rows = session.query(SupplyDemandZone).filter_by(
            symbol=symbol, active=True
        ).order_by(SupplyDemandZone.formed_at.desc()).all()
        return rows
    finally:
        session.close()


def deactivate_sd_zone(symbol: str, zone_type: str, s1: float):
    session = get_session()
    try:
        zone = session.query(SupplyDemandZone).filter_by(
            symbol=symbol, zone_type=zone_type, s1=s1
        ).first()
        if zone:
            zone.active = False
            zone.hit_count += 1
            zone.updated_at = datetime.utcnow()
            session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"deactivate_sd_zone error: {e}")
    finally:
        session.close()
