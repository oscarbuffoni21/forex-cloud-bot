import csv
import itertools
import statistics
from datetime import datetime
import pandas as pd
import time
import os

# === SETTINGS ===
DATA_FILES = ["EUR_USD_15m.csv", "GBP_USD_15m.csv", "USD_JPY_15m.csv"]
RSI_PERIODS = [21]
BUY_THRESHOLDS = [25]
SELL_THRESHOLDS = [65]
ATR_MULTIPLIERS = [1.5]
MIN_SLS = [0.0005]
TP_SL_RATIOS = [2.5]
FEE_PER_TRADE = 5

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
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(trs[-period:]) / period

def simulate_exit(entry, direction, sl, tp, future_highs, future_lows, fee):
    for high, low in zip(future_highs, future_lows):
        if direction == "buy":
            if low <= sl and high >= tp:
                return (sl - entry) * 1000 - fee
            elif low <= sl:
                return (sl - entry) * 1000 - fee
            elif high >= tp:
                return (tp - entry) * 1000 - fee
        elif direction == "sell":
            if high >= sl and low <= tp:
                return (entry - sl) * 1000 - fee
            elif high >= sl:
                return (entry - sl) * 1000 - fee
            elif low <= tp:
                return (entry - tp) * 1000 - fee
    mid = (future_highs[-1] + future_lows[-1]) / 2
    return (mid - entry) * 1000 - fee if direction == "buy" else (entry - mid) * 1000 - fee
def run_strategy(symbol, candles, rsi_p, rsi_buy, rsi_sell, atr_mult, min_sl, tp_sl_ratio):
    trades = []
    closes = candles['close'].tolist()
    highs = candles['high'].tolist()
    lows = candles['low'].tolist()

    for i in range(20, len(candles) - 10):
        window_prices = closes[i - rsi_p - 1:i + 1]
        rsi = compute_rsi(window_prices, rsi_p)
        atr = compute_atr(candles.iloc[i - 14:i + 1].to_dict('records'), 14)
        if atr is None:
            continue
        sl_tp_dist = max(atr * atr_mult, min_sl)
        future_highs = highs[i + 1:i + 11]
        future_lows = lows[i + 1:i + 11]
        entry = closes[i]

        if rsi < rsi_buy:
            sl = entry - sl_tp_dist
            tp = entry + tp_sl_ratio * sl_tp_dist
            trades.append(simulate_exit(entry, "buy", sl, tp, future_highs, future_lows, FEE_PER_TRADE))

        elif rsi > rsi_sell:
            sl = entry + sl_tp_dist
            tp = entry - tp_sl_ratio * sl_tp_dist
            trades.append(simulate_exit(entry, "sell", sl, tp, future_highs, future_lows, FEE_PER_TRADE))

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

# === MULTI-PAIR BACKTEST ===
results = []
start = time.time()
print("\n🔍 Running backtests for all pairs...")

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

    for combo in itertools.product(RSI_PERIODS, BUY_THRESHOLDS, SELL_THRESHOLDS, ATR_MULTIPLIERS, MIN_SLS, TP_SL_RATIOS):
        print(f"Running {symbol} with: RSI={combo[0]}, Buy={combo[1]}, Sell={combo[2]}, ATRx={combo[3]}, SLmin={combo[4]}, TP/SL={combo[5]}")
        result = run_strategy(symbol, candles, *combo)
        results.append(result)
        print(f"✅ {symbol} → {result}")

print(f"\n⏱️ Total backtest time: {time.time() - start:.2f} seconds")

# === Save results ===
df = pd.DataFrame(results)
df.to_csv("multi_pair_backtest_results.csv", index=False)
print("✅ Results saved to multi_pair_backtest_results.csv")

# === Print top results ===
top = df[df.TotalTrades >= 3].sort_values(by="Profit", ascending=False).head(5)
print("\n🏆 Top Strategies:")
print(top.to_string(index=False))
