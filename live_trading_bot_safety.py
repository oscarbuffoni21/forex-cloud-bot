import asyncio
import aiohttp
import time
import statistics
import csv
from datetime import datetime
import os
import json

# === CONFIG ===
OANDA_STREAM_URL = "https://stream-fxpractice.oanda.com/v3/accounts/{account_id}/pricing/stream"
OANDA_API_URL = "https://api-fxpractice.oanda.com/v3"
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCOUNT_ID = os.getenv("ACCOUNT_ID")
INSTRUMENTS = ["USD_JPY"]
HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

# === STRATEGY PARAMETERS ===
RSI_PERIOD = 21
BUY_THRESH = 25
SELL_THRESH = 65
ATR_MULTIPLIER = 1.5
MIN_SL = 0.0005
TP_SL_RATIO = 2.5
SPREAD_LIMIT = 0.0003
MIN_MOMENTUM_MOVE = 0.0002
ATR_PERIOD = 9
TRADE_SIZE = 2000

# === STATE ===
last_prices = {symbol: [] for symbol in INSTRUMENTS}
active_trades = {symbol: None for symbol in INSTRUMENTS}

# === UTILITY FUNCTIONS ===
def compute_rsi(prices, period):
    if len(prices) < period + 1:
        return 50
    gains = [max(prices[i] - prices[i - 1], 0) for i in range(1, len(prices))]
    losses = [abs(min(prices[i] - prices[i - 1], 0)) for i in range(1, len(prices))]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    return 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss != 0 else 100

def compute_atr(price_history):
    if len(price_history) < ATR_PERIOD:
        return None
    diffs = [abs(price_history[i] - price_history[i - 1]) for i in range(1, len(price_history))]
    return sum(diffs[-ATR_PERIOD:]) / ATR_PERIOD

def log_trade_to_csv(trade_data, filename="trades.csv"):
    today = datetime.utcnow().date()
    trade_time = datetime.fromisoformat(trade_data["timestamp"]).date()
    if trade_time != today:
        return  # Skip logging if not today's trade

    file_exists = os.path.isfile(filename)
    with open(filename, 'a', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=trade_data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade_data)

async def place_order(symbol, units, atr, entry_price):
    sl_distance = max(atr * ATR_MULTIPLIER, MIN_SL)
    tp_distance = sl_distance * TP_SL_RATIO
    sl_price = round(entry_price - sl_distance, 5) if units > 0 else round(entry_price + sl_distance, 5)
    tp_price = round(entry_price + tp_distance, 5) if units > 0 else round(entry_price - tp_distance, 5)

    order = {
        "order": {
            "instrument": symbol,
            "units": str(units),
            "type": "MARKET",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": str(sl_price)},
            "takeProfitOnFill": {"price": str(tp_price)}
        }
    }

    print(f"\n🛒 {symbol}: Placing {'BUY' if units > 0 else 'SELL'} @ {entry_price:.5f} | SL: {sl_price} | TP: {tp_price}")
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/orders", headers=HEADERS, json=order) as r:
            resp_json = await r.json()
            print("📦 Order response:", resp_json)

    try:
        tx = resp_json["orderFillTransaction"]
        profit = float(tx.get("pl", 0))
        quote_profit = float(tx.get("quotePL", 0))
        balance = float(tx.get("accountBalance", 0))
        trade_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "instrument": symbol,
            "side": "BUY" if units > 0 else "SELL",
            "entry_price": round(entry_price, 5),
            "stop_loss": sl_price,
            "take_profit": tp_price,
            "atr": round(atr, 5),
            "position_size": units,
            "profit": profit,
            "currency": "USD",
            "account_balance": balance
        }
        log_trade_to_csv(trade_data)
    except Exception as e:
        print(f"⚠️ {symbol}: Failed to log trade profit: {e}")

# === MAIN STRATEGY ===
async def handle_price_update(symbol, bid, ask):
    mid_price = (bid + ask) / 2
    spread = ask - bid
    last_prices[symbol].append(mid_price)
    if len(last_prices[symbol]) > 100:
        last_prices[symbol].pop(0)

    atr = compute_atr(last_prices[symbol])
    rsi = compute_rsi(last_prices[symbol], RSI_PERIOD)
    recent_move = mid_price - last_prices[symbol][0]

    print(f"\n📈 {symbol}: Mid={mid_price:.5f} | RSI={rsi:.2f} | ATR={atr:.5f} | ΔPrice={recent_move:.5f} | Spread={spread:.5f}")

    if active_trades[symbol] and (time.time() - active_trades[symbol]["time"] > 300):
        print(f"⏹ {symbol}: Clearing stale trade")
        active_trades[symbol] = None

    if spread > SPREAD_LIMIT:
        print(f"⏸ {symbol}: Skipping — Spread too high")
        return

    if active_trades[symbol]:
        print(f"⏸ {symbol}: Skipping — Trade already active")
        return

    if atr is None or len(last_prices[symbol]) < RSI_PERIOD + 1:
        print(f"⏸ {symbol}: Not enough data")
        return

    if abs(recent_move) < MIN_MOMENTUM_MOVE:
        print(f"⏸ {symbol}: No momentum")
        return

    if rsi < BUY_THRESH:
        active_trades[symbol] = {"type": "buy", "time": time.time()}
        await place_order(symbol, TRADE_SIZE, atr, mid_price)
    elif rsi > SELL_THRESH:
        active_trades[symbol] = {"type": "sell", "time": time.time()}
        await place_order(symbol, -TRADE_SIZE, atr, mid_price)

# === PRICE STREAM ===
async def stream_prices():
    url = OANDA_STREAM_URL.format(account_id=ACCOUNT_ID)
    params = {"instruments": ",".join(INSTRUMENTS)}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS, params=params) as resp:
            async for line in resp.content:
                if line:
                    try:
                        msg = line.decode("utf-8").strip()
                        if "bids" in msg and "asks" in msg:
                            data = json.loads(msg)
                            symbol = data["instrument"]
                            bid = float(data["bids"][0]["price"])
                            ask = float(data["asks"][0]["price"])
                            await handle_price_update(symbol, bid, ask)
                    except Exception as e:
                        print("❌ Error in stream processing:", e)

# === RUNNER ===
async def keep_stream_alive():
    while True:
        try:
            await stream_prices()
        except asyncio.CancelledError:
            print("🛑 Cancelled by user")
            break
        except Exception as e:
            print(f"⚠️ Stream error: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    print(f"🚀 Starting multi-currency trading bot for: {', '.join(INSTRUMENTS)}")
    asyncio.run(keep_stream_alive())
