"""
backtest.py
Backtester — run strategies against historical data before live trading.

Usage:
  python backtest.py --symbol SPY --start 2022-01-01 --end 2024-01-01
  python backtest.py --symbol AAPL --strategy momentum
"""

import argparse
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf
from loguru import logger

from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy


# ── Engine ────────────────────────────────────────────────────────────────────

class Backtester:

    def __init__(self, strategy, initial_capital: float = 10_000,
                 stop_loss_pct: float = 0.02, take_profit_pct: float = 0.04,
                 commission: float = 0.001):
        self.strategy = strategy
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.commission = commission  # 0.1% per trade

        self.position = 0
        self.avg_cost = 0
        self.stop_loss_price = 0
        self.take_profit_price = 0

        self.trades = []
        self.equity_curve = []

    def run(self, df: pd.DataFrame, symbol: str) -> dict:
        logger.info(f"Running backtest: {symbol} | {len(df)} bars | "
                    f"${self.initial_capital:,.0f} starting capital")

        for i in range(50, len(df)):
            window = df.iloc[:i]
            row = df.iloc[i]
            price = row["Close"]
            ts = row.name

            # Check stop-loss / take-profit if in position
            if self.position > 0:
                if price <= self.stop_loss_price:
                    self._sell(price, ts, "stop_loss")
                    continue
                if price >= self.take_profit_price:
                    self._sell(price, ts, "take_profit")
                    continue

            # Rename columns for strategy compatibility
            window_renamed = window.rename(columns={
                "Open":"open","High":"high","Low":"low",
                "Close":"close","Volume":"volume"
            })
            signal = self.strategy.generate_signal(symbol, window_renamed)

            if signal:
                if signal["action"] == "BUY" and self.position == 0:
                    self._buy(price, ts, signal["confidence"])
                elif signal["action"] == "SELL" and self.position > 0:
                    self._sell(price, ts, "signal")

            # Record equity
            equity = self.capital + (self.position * price if self.position > 0 else 0)
            self.equity_curve.append({"date": ts, "equity": equity})

        # Close any open position at end
        if self.position > 0:
            final_price = df.iloc[-1]["Close"]
            self._sell(final_price, df.iloc[-1].name, "end_of_test")

        return self._calc_stats(df)

    def _buy(self, price: float, ts, confidence: float):
        max_invest = self.capital * min(0.95, confidence)
        shares = int(max_invest / price)
        if shares == 0:
            return
        cost = shares * price * (1 + self.commission)
        self.capital -= cost
        self.position = shares
        self.avg_cost = price
        self.stop_loss_price = price * (1 - self.stop_loss_pct)
        self.take_profit_price = price * (1 + self.take_profit_pct)
        self.trades.append({
            "date": ts, "side": "BUY", "price": price,
            "shares": shares, "cost": cost, "pnl": 0
        })

    def _sell(self, price: float, ts, reason: str):
        proceeds = self.position * price * (1 - self.commission)
        cost_basis = self.position * self.avg_cost
        pnl = proceeds - cost_basis
        self.capital += proceeds
        self.trades[-1 if self.trades else 0]  # update last trade
        self.trades.append({
            "date": ts, "side": "SELL", "price": price,
            "shares": self.position, "proceeds": proceeds,
            "pnl": pnl, "reason": reason
        })
        self.position = 0
        self.avg_cost = 0

    def _calc_stats(self, df: pd.DataFrame) -> dict:
        if not self.trades:
            return {"error": "No trades executed"}

        sell_trades = [t for t in self.trades if t["side"] == "SELL"]
        if not sell_trades:
            return {"error": "No completed trades"}

        pnls = [t["pnl"] for t in sell_trades]
        total_return = (self.capital - self.initial_capital) / self.initial_capital

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        equity = pd.DataFrame(self.equity_curve).set_index("date")["equity"]
        rolling_max = equity.cummax()
        drawdown = (equity - rolling_max) / rolling_max
        max_drawdown = drawdown.min()

        daily_returns = equity.pct_change().dropna()
        sharpe = (daily_returns.mean() / daily_returns.std()) * (252 ** 0.5) if daily_returns.std() > 0 else 0

        stats = {
            "strategy": self.strategy.NAME,
            "initial_capital": self.initial_capital,
            "final_capital": round(self.capital, 2),
            "total_return_pct": round(total_return * 100, 2),
            "total_trades": len(sell_trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(len(wins) / max(len(sell_trades), 1) * 100, 1),
            "avg_win": round(np.mean(wins), 2) if wins else 0,
            "avg_loss": round(np.mean(losses), 2) if losses else 0,
            "profit_factor": round(sum(wins) / max(abs(sum(losses)), 1), 2),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "best_trade": round(max(pnls), 2),
            "worst_trade": round(min(pnls), 2),
        }
        return stats


# ── CLI ───────────────────────────────────────────────────────────────────────

def print_results(stats: dict):
    print("\n" + "=" * 50)
    print(f"  BACKTEST RESULTS — {stats.get('strategy', '?')}")
    print("=" * 50)
    for k, v in stats.items():
        if k == "strategy": continue
        label = k.replace("_", " ").title()
        if "pct" in k or "rate" in k:
            print(f"  {label:<25} {v}%")
        elif "capital" in k or "trade" in k.lower() and "trades" not in k:
            print(f"  {label:<25} ${v:,.2f}")
        else:
            print(f"  {label:<25} {v}")
    print("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Algo Trader Backtester")
    parser.add_argument("--symbol", default="SPY", help="Stock symbol (default: SPY)")
    parser.add_argument("--start",  default="2021-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end",    default="2024-01-01", help="End date YYYY-MM-DD")
    parser.add_argument("--capital",default=10000, type=float, help="Starting capital")
    parser.add_argument("--strategy", default="both",
                        choices=["momentum", "mean_reversion", "both"])
    args = parser.parse_args()

    logger.info(f"Downloading {args.symbol} data {args.start} → {args.end}...")
    df = yf.download(args.symbol, start=args.start, end=args.end, auto_adjust=True)

    if df.empty:
        logger.error("No data downloaded — check symbol and dates")
        exit(1)

    logger.info(f"Downloaded {len(df)} bars")

    strats = []
    if args.strategy in ("momentum", "both"):
        strats.append(MomentumStrategy())
    if args.strategy in ("mean_reversion", "both"):
        strats.append(MeanReversionStrategy())

    for strat in strats:
        bt = Backtester(strat, initial_capital=args.capital)
        stats = bt.run(df.copy(), args.symbol)
        print_results(stats)

    # Buy-and-hold comparison
    bh_return = (df["Close"].iloc[-1] - df["Close"].iloc[0]) / df["Close"].iloc[0] * 100
    print(f"\n  📊 Buy & Hold {args.symbol}: {bh_return:.1f}% over same period")
