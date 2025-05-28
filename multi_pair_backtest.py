import csv
import os
import time
import itertools
import statistics
import pandas as pd
from datetime import datetime
from tqdm import tqdm

# === SETTINGS ===
DATA_FILES = ["USD_JPY_15m.csv"]
RSI_PERIODS = [14]
BUY_THRESHOLDS = [20]
SELL_THRESHOLDS = [80]
ATR_MULTIPLIERS = [1.0, 1.2]
MIN_SLS = [0.03]
TP_SL_RATIOS = [2.0]
FEE_PER_TRADE = 1

# === Reset trade log ===
if os.path.exists("trades.csv"):
    os.remove("trades.csv")

# === INDICATORS ===
def compute_rsi(prices, period):
    if len(prices) < period + 1:
        return 50
    gains = [max(prices[i] - prices[i - 1], 0) for i in range(1, len(prices))]
    losses = [abs(min(prices[i] - prices[i - 1], 0)) for i in range(1, len(prices))]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    return 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss != 0 else 100

def compute_atr(candles, period):
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        high = candles[i]['high']
        low = candles[i]['low']
        prev_close = candles[i - 1]['close']
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return max(sum(trs[-period:]) / period, 1e-4)  # Avoid tiny ATRs

# === Exit Simulation ===
def simulate_exit(entry, direction, sl, tp, future_highs, future_lows):
    for high, low in zip(future_highs, future_lows):
        if direction == "buy":
            if low <= sl and high >= tp:
                return (sl - entry) * 1000 - FEE_PER_TRADE
            elif low <= sl:
                return (sl - entry) * 1000 - FEE_PER_TRADE
            elif high >= tp:
                return (tp - entry) * 1000 - FEE_PER_TRADE
        elif direction == "sell":
            if high >= sl and low <= tp:
                return (entry - sl) * 1000 - FEE_PER_TRADE
            elif high >= sl:
                return (entry - sl) * 1000 - FEE_PER_TRADE
            elif low <= tp:
                return (entry - tp) * 1000 - FEE_PER_TRADE
    mid = (future_highs[-1] + future_lows[-1]) / 2
    return (mid - entry) * 1000 - FEE_PER_TRADE if direction == "buy" else (entry - mid) * 1000 - FEE_PER_TRADE

# === Trade Logger ===
def log_trade(symbol, side, entry, sl, tp, profit, balance):
    data = {
        "time": datetime.utcnow().isoformat(),
        "instrument": symbol,
        "side": side,
        "entry_price": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "profit": round(profit, 4),
        "currency": "USD",
        "account_balance": balance,  # Just for log visibility
        "outcome": "WIN" if profit > 0 else "LOSS"
    }
    file_exists = os.path.isfile("trades.csv")
    with open("trades.csv", "a", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)

# === Strategy Runner ===
def run_strategy(symbol, candles, rsi_p, rsi_buy, rsi_sell, atr_mult, min_sl, tp_sl_ratio):
    trades = []
    closes = candles['close'].tolist()
    highs = candles['high'].tolist()
    lows = candles['low'].tolist()

    for i in range(20, len(candles) - 10):
        window_prices = closes[i - rsi_p - 1:i + 1]
        rsi = compute_rsi(window_prices, rsi_p)
        if i % 100 == 0:
            entry = closes[i]
            atr = compute_atr(candles.iloc[i - 14:i + 1].to_dict('records'), 14)
            if atr is None:
                continue
            sl_tp_dist = max(atr * atr_mult, min_sl)
            print(f"DEBUG | i={i} | RSI={rsi:.2f}, Buy<{rsi_buy}, Sell>{rsi_sell}, Entry={entry:.5f}, SL/TP Dist={sl_tp_dist:.5f}")
        atr = compute_atr(candles.iloc[i - 14:i + 1].to_dict('records'), 14)
        if atr is None:
            continue
        sl_tp_dist = max(atr * atr_mult, min_sl)
        future_highs = highs[i + 1:i + 11]
        future_lows = lows[i + 1:i + 11]
        entry = closes[i]

        recent_avg = sum(closes[i-5:i]) / 5
        if rsi < rsi_buy and entry < recent_avg * 0.995:
            continue  # Skip BUY if price is below recent average (adjusted)
        if rsi > rsi_sell and entry > recent_avg * 1.005:
            continue  # Skip SELL if price is above recent average (adjusted)

        balance = 1000 if not trades else 1000 + sum(trades)
        risk_per_trade = 0.02 * balance  # 2% risk per trade
        units = risk_per_trade / sl_tp_dist

        if rsi < rsi_buy:
            sl = entry - sl_tp_dist
            tp = entry + tp_sl_ratio * sl_tp_dist
            profit = simulate_exit(entry, "buy", sl, tp, future_highs, future_lows) * (units / 1000)
            trades.append(profit)
            log_trade(symbol, "BUY", entry, sl, tp, profit, balance + profit)

        elif rsi > rsi_sell:
            sl = entry + sl_tp_dist
            tp = entry - sl_tp_dist
            profit = simulate_exit(entry, "sell", sl, tp, future_highs, future_lows) * (units / 1000)
            trades.append(profit)
            log_trade(symbol, "SELL", entry, sl, tp, profit, balance + profit)

    total = sum(trades)
    win_rate = (len([t for t in trades if t > 0]) / len(trades)) * 100 if trades else 0
    return {
        "Symbol": symbol,
        "RSI_PERIOD": rsi_p,
        "BUY_THRESH": rsi_buy,
        "SELL_THRESH": rsi_sell,
        "ATR_MULTIPLIER": atr_mult,
        "MIN_SL": min_sl,
        "TP_SL_RATIO": tp_sl_ratio,
        "TotalTrades": len(trades),
        "Profit": round(total, 2),
        "WinRate": round(win_rate, 2)
    }

# === Multi-Pair Backtest ===
results = []
start = time.time()
print("\n🔍 Running backtests for all pairs...")

PAIR_SETTINGS = {
    "USD_JPY": {
        "RSI_PERIODS": [10, 14, 21],
        "BUY_THRESHOLDS": [20, 25, 30],
        "SELL_THRESHOLDS": [70, 75, 80],
        "ATR_MULTIPLIERS": [1.0, 1.5, 2.0],
        "MIN_SLS": [0.02, 0.03],
        "TP_SL_RATIOS": [1.0, 1.5, 2.0]
    }
}

for file in DATA_FILES:
    symbol = file.replace("_15m.csv", "")
    if os.path.getsize(file) == 0:
        print(f"⚠️ Skipping {file} — file is empty.")
        continue

    try:
        candles = pd.read_csv(file)
        if candles.empty or 'close' not in candles.columns:
            print(f"⚠️ Skipping {file} — invalid or missing columns.")
            continue
    except Exception as e:
        print(f"⚠️ Failed to load {file}: {e}")
        continue

    settings = PAIR_SETTINGS.get(symbol, None)
    if settings is None:
        continue
    all_combos = list(itertools.product(
        settings["RSI_PERIODS"],
        settings["BUY_THRESHOLDS"],
        settings["SELL_THRESHOLDS"],
        settings["ATR_MULTIPLIERS"],
        settings["MIN_SLS"],
        settings["TP_SL_RATIOS"]
    ))
    for combo in tqdm(all_combos, desc=f"🔄 Optimizing {symbol}", unit="combo"):
        result = run_strategy(symbol, candles, *combo)
        results.append(result)

print(f"\n⏱️ Total backtest time: {time.time() - start:.2f} seconds")

# === Save results ===
df = pd.DataFrame(results)
df.to_csv("multi_pair_backtest_results.csv", index=False)
print("✅ Results saved to multi_pair_backtest_results.csv")

# === Print top results ===
top = df[df.TotalTrades >= 3].sort_values(by="Profit", ascending=False).head(5)
print("\n🏆 Top Strategies:")
print(top.to_string(index=False))

# === Expose for dashboard
def run_backtest():
    return pd.read_csv("multi_pair_backtest_results.csv").to_dict(orient="records")