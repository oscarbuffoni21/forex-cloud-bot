import asyncio
import aiohttp
import time
import statistics
import uuid
import csv
from datetime import datetime

# === CONFIG ===
OANDA_STREAM_URL = "https://stream-fxpractice.oanda.com/v3/accounts/{account_id}/pricing/stream"
OANDA_API_URL = "https://api-fxpractice.oanda.com/v3"
ACCESS_TOKEN = "REPLACE_ME"
ACCOUNT_ID = "REPLACE_ME"
INSTRUMENT = "EUR_USD"
HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

# === STRATEGY PARAMETERS ===
ATR_PERIOD = 10
ATR_MULTIPLIER = 1.5
MIN_MOMENTUM_MOVE = 0.0002
SPREAD_LIMIT = 0.0003
TRADE_SIZE = 1000  # Units

# === STATE ===
last_prices = []
active_trade = None

# === UTILITY FUNCTIONS ===

def compute_atr(price_history):
    if len(price_history) < ATR_PERIOD:
        return None
    diffs = [abs(price_history[i] - price_history[i - 1]) for i in range(1, len(price_history))]
    return sum(diffs[-ATR_PERIOD:]) / ATR_PERIOD

def log_trade_to_csv(trade_data, filename="trades.csv"):
    file_exists = False
    try:
        with open(filename, 'r'):
            file_exists = True
    except FileNotFoundError:
        pass

    with open(filename, 'a', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=trade_data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade_data)

async def place_order(units, atr, entry_price):
    sl_price = None
    tp_price = None

    if units > 0:  # BUY
        sl_price = round(entry_price - atr * ATR_MULTIPLIER, 5)
        tp_price = round(entry_price + atr * ATR_MULTIPLIER * 2, 5)
    else:  # SELL
        sl_price = round(entry_price + atr * ATR_MULTIPLIER, 5)
        tp_price = round(entry_price - atr * ATR_MULTIPLIER * 2, 5)

    order = {
        "order": {
            "instrument": INSTRUMENT,
            "units": str(units),
            "type": "MARKET",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": str(sl_price)},
            "takeProfitOnFill": {"price": str(tp_price)}
        }
    }

    print(f"🛒 Placing order: {'BUY' if units > 0 else 'SELL'} @ {entry_price:.5f} | SL: {sl_price} | TP: {tp_price}")

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/orders", headers=HEADERS, json=order) as r:
            resp_json = await r.json()
            print(f"📦 Order response: {resp_json}")

    # Log to CSV
    log_trade_to_csv({
        "timestamp": datetime.utcnow().isoformat(),
        "instrument": INSTRUMENT,
        "side": "BUY" if units > 0 else "SELL",
        "entry_price": round(entry_price, 5),
        "stop_loss": sl_price,
        "take_profit": tp_price,
        "atr": round(atr, 5),
        "units": units
    })

# === MAIN STRATEGY ===

async def handle_price_update(bid, ask):
    global last_prices, active_trade

    mid_price = (bid + ask) / 2
    spread = ask - bid
    print(f"📈 Price update: Bid={bid:.5f} Ask={ask:.5f} Spread={spread:.5f}")

    last_prices.append(mid_price)
    if len(last_prices) > ATR_PERIOD + 5:
        last_prices.pop(0)

    if spread > SPREAD_LIMIT or active_trade:
        return

    atr = compute_atr(last_prices)
    if atr is None:
        return

    recent_move = mid_price - last_prices[0]

    if abs(recent_move) > MIN_MOMENTUM_MOVE:
        trade_type = "buy" if recent_move > 0 else "sell"
        units = TRADE_SIZE if trade_type == "buy" else -TRADE_SIZE
        print(f"🔁 Momentum detected: {trade_type.upper()} @ {mid_price:.5f} | ATR: {atr:.5f}")

        active_trade = {
            "type": trade_type,
            "entry_price": mid_price,
            "atr": atr,
            "time": time.time()
        }

        await place_order(units, atr, mid_price)

# === STREAM LISTENER ===

async def stream_prices():
    url = OANDA_STREAM_URL.format(account_id=ACCOUNT_ID)
    params = {"instruments": INSTRUMENT}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS, params=params) as resp:
            async for line in resp.content:
                if line:
                    try:
                        msg = line.decode("utf-8").strip()
                        if "bids" in msg and "asks" in msg:
                            import json
                            data = json.loads(msg)
                            bid = float(data["bids"][0]["price"])
                            ask = float(data["asks"][0]["price"])
                            await handle_price_update(bid, ask)
                    except Exception as e:
                        print("Error processing message:", e)

# === KEEP ALIVE ===

async def keep_stream_alive():
    while True:
        try:
            await stream_prices()
        except asyncio.CancelledError:
            print("❌ Cancelled by user (Ctrl+C)")
            break
        except Exception as e:
            print(f"⚠️ Stream error: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

# === ENTRY POINT ===

if __name__ == "__main__":
    print(f"🚀 Starting live trading bot for {INSTRUMENT}")
    asyncio.run(keep_stream_alive())
    # Test log only — comment out after running once
log_trade_to_csv({
    "timestamp": datetime.utcnow().isoformat(),
    "instrument": "EUR_USD",
    "side": "BUY",
    "entry_price": 1.12345,
    "stop_loss": 1.12200,
    "take_profit": 1.12600,
    "atr": 0.00075,
    "units": 1000
})