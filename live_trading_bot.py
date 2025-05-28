def is_support_resistance_level(prices, current_price, threshold=0.0003):
    if len(prices) < 20:
        return False
    highs = max(prices[-20:])
    lows = min(prices[-20:])
    return abs(current_price - highs) < threshold or abs(current_price - lows) < threshold
import asyncio
import aiohttp
import time
import statistics
import csv
from datetime import datetime
import os
import json
import platform
import subprocess
from collections import defaultdict
import matplotlib.pyplot as plt
import base64
from io import BytesIO
daily_summary = defaultdict(list)

# Track closed trades to avoid duplicate alerts
seen_closed_trades = set()

TELEGRAM_BOT_TOKEN = "7653720492:AAGXkXE3WcYW-fF3pDDvTWgrHxfr5Parnvk"
TELEGRAM_CHAT_ID = "7575905919"

async def send_telegram_alert(message, session):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        await session.post(url, json=payload)
    except Exception as e:
        print(f"❌ Telegram alert failed: {e}")

# Utility to fetch Telegram chat ID
async def get_telegram_chat_id(session):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    async with session.get(url) as response:
        data = await response.json()
        print("🔍 Chat ID lookup:", json.dumps(data, indent=2))

# === CONFIG ===
OANDA_STREAM_URL = "https://stream-fxpractice.oanda.com/v3/accounts/{account_id}/pricing/stream"
OANDA_API_URL = "https://api-fxpractice.oanda.com/v3"
ACCESS_TOKEN = "29311d57933f296890c32f56286ed54f-801350f3b7ce5aebe90fb3c8633d0e9d"
ACCOUNT_ID = "101-004-31712326-001"
INSTRUMENTS = ["USD_JPY"]
HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

# === STRATEGY PARAMETERS ===
RSI_PERIOD = 5
BUY_THRESH = 35
SELL_THRESH = 65
TP_SL_RATIO = 1.2
ATR_MULTIPLIER = 0.8
MIN_SL = 0.0003
ATR_PERIOD = 5
RISK_PERCENT = 0.02  # 2% risk per trade
def calculate_trade_size(account_balance, sl_distance, symbol):
    pip_value = 0.01 if not symbol.endswith("_JPY") else 0.001
    risk_amount = account_balance * RISK_PERCENT
    pip_risk = sl_distance / pip_value
    unit_value = risk_amount / pip_risk
    return int(unit_value)
MIN_MOMENTUM_MOVE = 0.0002

# === STATE ===
last_prices = {symbol: [] for symbol in INSTRUMENTS}
active_trades = {symbol: None for symbol in INSTRUMENTS}
max_open_trades = 3
last_trade_times = {symbol: 0 for symbol in INSTRUMENTS}

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
    file_exists = os.path.isfile(filename)
    with open(filename, 'a', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=trade_data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade_data)

async def manage_trailing_stop(symbol, trade_id, entry_price, units, session):
    precision = 3 if symbol.endswith("_JPY") else 5
    pip = 0.01 if not symbol.endswith("_JPY") else 0.001
    trail_trigger_pips = 5  # trigger after 5 pips in profit
    trail_gap_pips = 2      # keep SL 2 pips behind
    last_sl_price = None
    partial_closed = False

    while True:
        await asyncio.sleep(5)
        try:
            # Fetch latest price
            url = f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/pricing?instruments={symbol}"
            async with session.get(url, headers=HEADERS) as r:
                data = await r.json()
                bids = data["prices"][0]["bids"]
                asks = data["prices"][0]["asks"]
                bid = float(bids[0]["price"])
                ask = float(asks[0]["price"])
                current_price = bid if units < 0 else ask

            profit_pips = (entry_price - current_price) / pip if units < 0 else (current_price - entry_price) / pip

            # --- FORCE CLOSE IF DECENT PROFIT (e.g., 10+ pips) ---
            if profit_pips >= 10:
                print(f"💸 {symbol}: Decent profit reached (+{profit_pips:.1f} pips). Closing full trade.")
                await send_telegram_alert(f"💸 {symbol}: Decent profit (+{profit_pips:.1f} pips) — Closing trade.", session)
                close_order = {
                    "order": {
                        "instrument": symbol,
                        "units": str(-units),
                        "type": "MARKET",
                        "timeInForce": "FOK",
                        "positionFill": "DEFAULT"
                    }
                }
                async with session.post(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/orders", headers=HEADERS, json=close_order) as r:
                    resp = await r.json()
                    print(f"💥 Early close response: {json.dumps(resp, indent=2)}")
                return

            # --- PARTIAL CLOSE at +5 pips ---
            if profit_pips >= 5 and not partial_closed:
                close_units = int(units / 2)
                # For buys, close negative units; for sells, close positive units
                close_units_to_send = -close_units if units > 0 else -close_units
                close_order = {
                    "order": {
                        "instrument": symbol,
                        "units": str(close_units_to_send),
                        "type": "MARKET",
                        "timeInForce": "FOK",
                        "positionFill": "REDUCE_ONLY"
                    }
                }
                async with session.post(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/orders", headers=HEADERS, json=close_order) as r:
                    resp = await r.json()
                    print(f"💰 Closed 50% at +5 pips: {resp}")
                    # Telegram alert for 50% close at +5 pips
                    await send_telegram_alert(f"📤 {symbol}: Closed 50% at +5 pips", session)
                    partial_closed = True

                # --- Set hard TP for remaining half at ±10 pips ---
                # Set TP for remaining half at +10 pips
                fixed_tp_price = round(entry_price - 10 * pip, precision) if units < 0 else round(entry_price + 10 * pip, precision)
                tp_order = {
                    "order": {
                        "type": "TAKE_PROFIT",
                        "tradeID": trade_id,
                        "price": f"{fixed_tp_price:.5f}",
                        "timeInForce": "GTC",
                        "triggerCondition": "DEFAULT"
                    }
                }
                async with session.post(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/orders", headers=HEADERS, json=tp_order) as tp_resp:
                    tp_data = await tp_resp.json()
                    if "orderCreateTransaction" in tp_data:
                        print(f"🎯 Fixed TP set at {fixed_tp_price}")
                        # Telegram alert for fixed TP set
                        await send_telegram_alert(f"🎯 {symbol}: Fixed TP set at {fixed_tp_price}", session)
                    else:
                        print(f"⚠️ Failed to set fixed TP: {json.dumps(tp_data, indent=2)}")

                # Move SL to entry +1 pip (buys) or entry -1 pip (sells)
                new_sl_price = round(entry_price + pip, precision) if units > 0 else round(entry_price - pip, precision)
                sl_order = {
                    "order": {
                        "type": "STOP_LOSS",
                        "tradeID": trade_id,
                        "price": f"{new_sl_price:.5f}",
                        "timeInForce": "GTC",
                        "triggerCondition": "DEFAULT",
                        "replaceExisting": True
                    }
                }
                async with session.post(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/orders", headers=HEADERS, json=sl_order) as sr:
                    sl_resp = await sr.json()
                    if "orderCreateTransaction" in sl_resp:
                        print(f"🔐 SL moved to breakeven (+1 pip): {new_sl_price}")
                        # Telegram alert for SL moved to breakeven
                        await send_telegram_alert(f"🔐 {symbol}: SL moved to breakeven (+1 pip)", session)
                        last_sl_price = new_sl_price
                    else:
                        print(f"⚠️ Failed to move SL to breakeven: {json.dumps(sl_resp, indent=2)}")

            # --- TRAILING SL for remaining position ---
            if profit_pips >= trail_trigger_pips:
                trail_price = round(current_price - (trail_gap_pips * pip), precision) if units > 0 else round(current_price + (trail_gap_pips * pip), precision)
                if trail_price != last_sl_price:
                    sl_order = {
                        "order": {
                            "type": "STOP_LOSS",
                            "tradeID": trade_id,
                            "price": f"{trail_price:.5f}",
                            "timeInForce": "GTC",
                            "triggerCondition": "DEFAULT",
                            "replaceExisting": True
                        }
                    }
                    async with session.post(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/orders", headers=HEADERS, json=sl_order) as sr:
                        resp = await sr.json()
                        if "orderCreateTransaction" in resp:
                            print(f"🔧 SL trailed to {trail_price}")
                            # Telegram alert for SL trailed
                            await send_telegram_alert(f"🔧 {symbol}: SL trailed to {trail_price}", session)
                            last_sl_price = trail_price
                        else:
                            print(f"⚠️ Failed to update trailing SL: {json.dumps(resp, indent=2)}")

        except Exception as e:
            print(f"⚠️ Trailing stop error: {e}")

async def place_order(symbol, atr, entry_price, session, bid=None, ask=None):
    precision = 3 if symbol.endswith("_JPY") else 5

    # account_balance and SL/TP calculation for dynamic position size
    # We need to estimate SL/TP based on entry price and ATR
    base_distance = max(0.0015, atr * 2.5 if atr else 0.002)
    tp_distance = base_distance * TP_SL_RATIO
    buffer = max(0.0005, base_distance * 1.5)
    # Default is buy unless bid/ask provided
    units_sign = 1
    if bid is not None and ask is not None:
        units_sign = 1 if entry_price == ask else -1 if entry_price == bid else 1
    # Simulate buy/sell guess based on context
    if units_sign > 0:
        sl_price = round(entry_price - base_distance - buffer, precision)
        tp_price = round(entry_price + tp_distance, precision)
    else:
        sl_price = round(entry_price + base_distance + buffer, precision)
        tp_price = round(entry_price - tp_distance, precision)
    # Dynamically calculate trade size
    # Fallback account_balance (will be updated after fill, but use 1000.0 for now)
    account_balance = 1000.0
    sl_distance = abs(tp_price - sl_price)
    units = calculate_trade_size(account_balance, sl_distance, symbol)
    units = max(100, int(units))  # Ensure at least minimum trade size

    print(f"\n🛒 {symbol}: Placing {'BUY' if units > 0 else 'SELL'} MARKET @ {entry_price:.5f}")

    market_order = {
        "order": {
            "instrument": symbol,
            "units": str(units),
            "type": "MARKET",
            "timeInForce": "FOK",
            "positionFill": "DEFAULT"
        }
    }

    async with session.post(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/orders", headers=HEADERS, json=market_order) as r:
        resp = await r.json()
        tx_id = resp.get("lastTransactionID")

    await asyncio.sleep(1)

    async with session.get(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/transactions/{tx_id}", headers=HEADERS) as r:
        tx_data = await r.json()
        with open("last_transaction_debug.json", "w") as f:
            json.dump(tx_data, f, indent=2)
        fill = tx_data.get("orderFillTransaction") or tx_data.get("transaction")
        if not fill or ("tradeOpened" not in fill and "tradesClosed" not in fill):
            print("❌ Market order not filled.")
            print("🧾 Full response:", json.dumps(tx_data, indent=2))
            await send_telegram_alert(f"❌ {symbol}: Market order not filled", session)
            active_trades[symbol] = None
            return False

        trade_id = None
        if "tradeOpened" in fill:
            trade_id = fill["tradeOpened"].get("tradeID")
        elif "tradesOpened" in fill and isinstance(fill["tradesOpened"], list) and len(fill["tradesOpened"]) > 0:
            trade_id = fill["tradesOpened"][0].get("tradeID")
        filled_price = float(fill.get("price", entry_price))
        realized_pl = float(fill.get("pl", 0))

        # Recalculate SL/TP based on actual filled price
        base_distance = max(0.0015, atr * 2.5 if atr else 0.002)
        tp_distance = base_distance * TP_SL_RATIO
        buffer = max(0.0005, base_distance * 1.5)
        if units > 0:
            sl_price = round(filled_price - base_distance - buffer, precision)
            tp_price = round(filled_price + tp_distance, precision)
        else:
            sl_price = round(filled_price + base_distance + buffer, precision)
            tp_price = round(filled_price - tp_distance, precision)

        print(f"🎯 SL: {sl_price:.5f} | TP: {tp_price:.5f} | Distance: {base_distance:.5f}")
        print(f"✅ Trade filled @ {filled_price:.5f} | ID: {trade_id}")
        await send_telegram_alert(f"✅ {symbol}: Trade filled @ {filled_price:.5f} | TP: {tp_price:.5f} | SL: {sl_price:.5f}", session)
        await send_telegram_alert(f"💰 Estimated PnL: £{realized_pl:.2f}", session)
        account_balance = float(fill.get("accountBalance", 0.0))
        await send_telegram_alert(f"📊 Account Balance: £{account_balance:.2f}", session)

    # Wait for price to move at least 0.0003 in our favor before setting TP/SL
    min_move = 0.0003
    wait_time = 0
    current = filled_price
    while wait_time < 15:
        await asyncio.sleep(1)
        wait_time += 1
        try:
            url = f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/pricing?instruments={symbol}"
            async with session.get(url, headers=HEADERS) as r:
                data = await r.json()
                current = float(data["prices"][0]["bids"][0]["price"]) if units < 0 else float(data["prices"][0]["asks"][0]["price"])
                if abs(current - filled_price) >= min_move:
                    break
        except:
            pass

    # If price hasn't moved enough, widen TP/SL
    if abs(current - filled_price) < min_move:
        base_distance *= 2
        base_distance = max(base_distance, 0.0015)
        tp_distance = base_distance * TP_SL_RATIO
        buffer = max(0.0005, base_distance * 1.1)
        print(f"⚠️ Price still too close after wait. Widening SL/TP distances.")
        if units > 0:
            sl_price = round(filled_price - base_distance - buffer, precision)
            tp_price = round(filled_price + tp_distance, precision)
        else:
            sl_price = round(filled_price + base_distance + buffer, precision)
            tp_price = round(filled_price - tp_distance, precision)

    # Double-check buffer distance again before creating TP/SL orders
    base_distance = max(base_distance, 0.0010 if symbol.endswith("_JPY") else 0.0001)
    # Now set TP and SL as separate orders
    tp_success, sl_success = False, False
    if trade_id:
        tp_order = {
            "order": {
                "type": "TAKE_PROFIT",
                "tradeID": trade_id,
                "price": f"{tp_price:.5f}",
                "timeInForce": "GTC",
                "triggerCondition": "DEFAULT"
            }
        }
        sl_order = {
            "order": {
                "type": "STOP_LOSS",
                "tradeID": trade_id,
                "price": f"{sl_price:.5f}",
                "timeInForce": "GTC",
                "triggerCondition": "DEFAULT"
            }
        }
        # Set TP
        try:
            async with session.post(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/orders", headers=HEADERS, json=tp_order) as tr:
                tp_resp = await tr.json()
                if "orderCreateTransaction" in tp_resp:
                    tp_success = True
                else:
                    print(f"⚠️ Failed to set TP: {json.dumps(tp_resp, indent=2)}")
        except Exception as e:
            print(f"⚠️ Exception setting TP: {e}")
        # Set SL
        try:
            async with session.post(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/orders", headers=HEADERS, json=sl_order) as sr:
                sl_resp = await sr.json()
                if "orderCreateTransaction" in sl_resp:
                    sl_success = True
                else:
                    print(f"⚠️ Failed to set SL: {json.dumps(sl_resp, indent=2)}")
        except Exception as e:
            print(f"⚠️ Exception setting SL: {e}")

        # Retry SL if failed
        for attempt in range(3):
            if sl_success:
                break
            print(f"🔁 Retrying SL setup (Attempt {attempt + 1})...")
            await asyncio.sleep(2)
            try:
                async with session.post(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/orders", headers=HEADERS, json=sl_order) as retry_sr:
                    retry_resp = await retry_sr.json()
                    if "orderCreateTransaction" in retry_resp:
                        sl_success = True
                        print(f"✅ SL set on retry attempt {attempt + 1}")
                    else:
                        print(f"⚠️ Retry SL failed: {json.dumps(retry_resp, indent=2)}")
            except Exception as e:
                print(f"⚠️ Exception during SL retry: {e}")

        # --- FORCE FAIL-SAFE EXIT IF SL or TP SETUP FAILS ---
        if not sl_success or not tp_success:
            print(f"🛑 SL or TP setup failed for {symbol} — closing trade immediately")
            await send_telegram_alert(f"🛑 {symbol}: SL/TP setup failed. Closing trade to avoid risk.", session)
            try:
                close_order = {
                    "order": {
                        "instrument": symbol,
                        "units": str(-units),
                        "type": "MARKET",
                        "timeInForce": "FOK",
                        "positionFill": "DEFAULT"
                    }
                }
                async with session.post(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/orders", headers=HEADERS, json=close_order) as r:
                    resp = await r.json()
                    print(f"🔐 Emergency close response: {json.dumps(resp, indent=2)}")
                    await send_telegram_alert(f"🔐 {symbol}: Trade closed due to failed SL/TP setup.", session)
            except Exception as e:
                print(f"❌ Emergency close failed: {e}")
            return False

    await asyncio.sleep(10)
    try:
        async with session.get(f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/openTrades", headers=HEADERS) as check_resp:
            trade_data = await check_resp.json()
            open_ids = {t["id"] for t in trade_data.get("trades", [])}
            if trade_id not in open_ids:
                print(f"⚠️ {symbol}: Trade ID {trade_id} missing from open trades, assuming SL not yet active")
                await send_telegram_alert(f"⚠️ {symbol}: Trade ID {trade_id} missing from open trades, retrying SL/TP setup", session)
                active_trades[symbol] = {
                    "type": "open",
                    "tradeID": trade_id,
                    "entry": filled_price,
                    "tp": tp_price,
                    "sl": sl_price,
                    "units": units,
                    "time": time.time()
                }
                return True
    except Exception as e:
        print(f"⚠️ Error checking trade presence: {e}")
        return False

    if trade_id:
        asyncio.create_task(manage_trailing_stop(symbol, trade_id, filled_price, units, session))

    if trade_id:
        log_trade_to_csv({
            "symbol": symbol,
            "entry": filled_price,
            "tp": tp_price,
            "sl": sl_price,
            "units": units,
            "time": datetime.utcnow().isoformat(),
            "profit": 0
        })

        profit = 0
        daily_summary[symbol].append({
            "entry": filled_price,
            "tp": tp_price,
            "sl": sl_price,
            "units": units,
            "time": datetime.utcnow().isoformat(),
            "profit": profit
        })

    # Only mark trade active if both SL and TP were set successfully
    if trade_id and sl_success and tp_success:
        trade_record = {
            "type": "open",
            "tradeID": trade_id,
            "entry": filled_price,
            "tp": tp_price,
            "sl": sl_price,
            "units": units,
            "time": time.time()
        }
        if not isinstance(active_trades[symbol], list):
            active_trades[symbol] = []
        active_trades[symbol].append(trade_record)
        await send_telegram_alert(f"🆕 {symbol}: Trade added to active list | ID: {trade_id}", session)
    else:
        print(f"🧼 {symbol}: SL or TP not set — will not mark as active")
        pass  # no need to reset the active_trades list

    return True

def get_dynamic_spread_limit():
    current_hour = datetime.utcnow().hour
    if 6 <= current_hour < 14:  # London session
        return 0.005
    elif 14 <= current_hour < 22:  # New York session
        return 0.02
    else:  # Asian session or off-hours
        return 0.012

import csv
from datetime import datetime

# ---- PnL tracking and engulfing pattern helpers ----
def update_daily_pnl():
    global daily_total_pnl
    try:
        with open("trades.csv", "r") as f:
            reader = csv.DictReader(f)
            today = datetime.utcnow().date()
            daily_total_pnl = sum(float(row["profit"]) for row in reader if datetime.fromisoformat(row["time"]).date() == today)
    except Exception:
        daily_total_pnl = 0

def is_bullish_engulfing(prices):
    if len(prices) < 3:
        return False
    o1, c1 = prices[-3], prices[-2]
    o2, c2 = prices[-2], prices[-1]
    return c2 > o2 and o1 > c1 and c2 > o1 and o2 < c1

def is_bearish_engulfing(prices):
    if len(prices) < 3:
        return False
    o1, c1 = prices[-3], prices[-2]
    o2, c2 = prices[-2], prices[-1]
    return c2 < o2 and o1 < c1 and c2 < o1 and o2 > c1

async def handle_price_update(symbol, bid, ask, session):
    # --- Minimal, clean version: strong confluence only, 1 open trade per symbol, daily loss cap, fixed size, clear alert ---
    mid = (bid + ask) / 2
    spread = ask - bid
    last_prices[symbol].append(mid)
    if len(last_prices[symbol]) > 100:
        last_prices[symbol].pop(0)

    update_daily_pnl()
    if 'daily_total_pnl' in globals() and daily_total_pnl <= -200:
        print(f"⛔ {symbol}: Daily loss limit reached ({daily_total_pnl:.2f})")
        return

    # Only 1 open trade per symbol
    # Max trades per symbol logic
    if isinstance(active_trades[symbol], list):
        pass
    elif active_trades[symbol] is not None:
        pass

    if len(last_prices[symbol]) < 21:
        return

    rsi = compute_rsi(last_prices[symbol], RSI_PERIOD)
    atr = compute_atr(last_prices[symbol])
    if not atr or atr < 0.0003:
        return

    # Calculate ATR median for adaptive RSI thresholds
    if len(last_prices[symbol]) >= 21:
        atr_list = []
        for i in range(1, min(len(last_prices[symbol]), 21)):
            atr_val = abs(last_prices[symbol][-i] - last_prices[symbol][-i - 1])
            atr_list.append(atr_val)
        if len(atr_list) >= 5:
            atr_median = statistics.median(atr_list[-20:]) if len(atr_list) >= 20 else statistics.median(atr_list)
        else:
            atr_median = atr
    else:
        atr_median = atr

    def adaptive_rsi_thresholds(rsi, atr, atr_median, base_buy=25, base_sell=75):
        if atr > 1.5 * atr_median:
            # Market is volatile: widen thresholds slightly
            buy_threshold = base_buy - 5  # e.g., 20
            sell_threshold = base_sell + 5  # e.g., 80
        elif atr < 0.75 * atr_median:
            # Market is calm: tighten thresholds slightly
            buy_threshold = base_buy + 3  # e.g., 28
            sell_threshold = base_sell - 3  # e.g., 72
        else:
            buy_threshold = base_buy
            sell_threshold = base_sell
        return buy_threshold, sell_threshold

    buy_thresh, sell_thresh = adaptive_rsi_thresholds(rsi, atr, atr_median, base_buy=BUY_THRESH, base_sell=SELL_THRESH)

    if spread > get_dynamic_spread_limit():
        return

    support_resistance = is_support_resistance_level(last_prices[symbol], mid)
    engulf_up = is_bullish_engulfing(last_prices[symbol])
    engulf_down = is_bearish_engulfing(last_prices[symbol])
    ma_short = statistics.mean(last_prices[symbol][-5:])
    ma_long = statistics.mean(last_prices[symbol][-20:])
    momentum_up = ma_short > ma_long
    momentum_down = ma_short < ma_long

    # --- Only trade if all confluence: Adaptive RSI + S/R + Engulfing + momentum ---
    if rsi < buy_thresh and support_resistance and engulf_up and momentum_up:
        msg = (f"📈 {symbol}: BUY Signal @ {mid:.5f} | RSI={rsi:.2f} | Adaptive RSI Buy Thresh={buy_thresh:.2f} | S/R: {support_resistance} | Bull Engulfing: {engulf_up} | Momentum: {momentum_up}")
        print(msg)
        await send_telegram_alert(msg, session)
        await place_order(symbol, atr, mid, session, bid=bid, ask=ask)
    elif rsi > sell_thresh and support_resistance and engulf_down and momentum_down:
        msg = (f"📉 {symbol}: SELL Signal @ {mid:.5f} | RSI={rsi:.2f} | Adaptive RSI Sell Thresh={sell_thresh:.2f} | S/R: {support_resistance} | Bear Engulfing: {engulf_down} | Momentum: {momentum_down}")
        print(msg)
        await send_telegram_alert(msg, session)
        await place_order(symbol, atr, mid, session, bid=bid, ask=ask)

async def stream_prices(session):
    url = OANDA_STREAM_URL.format(account_id=ACCOUNT_ID)
    params = {"instruments": ",".join(INSTRUMENTS)}
    async with session.get(url, headers=HEADERS, params=params) as resp:
        async for line in resp.content:
            if line:
                try:
                    msg = line.decode("utf-8").strip()
                    print(f"🔄 RAW STREAM: {msg[:100]}")
                    if "bids" in msg and "asks" in msg:
                        data = json.loads(msg)
                        symbol = data["instrument"]
                        bid = float(data["bids"][0]["price"])
                        ask = float(data["asks"][0]["price"])
                        await handle_price_update(symbol, bid, ask, session)
                except Exception as e:
                    print("❌ Error in stream processing:", e)

async def keep_stream_alive(session):
    while True:
        try:
            await stream_prices(session)
        except asyncio.CancelledError:
            print("🛑 Cancelled by user")
            break
        except Exception as e:
            print(f"⚠️ Stream error: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
        # Daily summary at 21:59 UTC
        if datetime.utcnow().hour == 21 and datetime.utcnow().minute == 59:
            await send_daily_summary(session)
        await asyncio.sleep(60)
async def send_daily_chart(symbol, prices, session):
    if not prices:
        return
    plt.figure()
    plt.plot(prices, label=symbol)
    plt.title(f"{symbol} Price Snapshot")
    plt.xlabel("Ticks")
    plt.ylabel("Mid Price")
    plt.legend()
    buf = BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode()
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": f"data:image/png;base64,{encoded}"
    }
    await session.post(url, json=payload)

async def send_daily_summary(session):
    if not daily_summary:
        return
    message_lines = ["📊 Daily Summary — Successful Trades"]
    for symbol, trades in daily_summary.items():
        message_lines.append(f"\n🔹 {symbol}: {len(trades)} trades")
        total_profit = 0
        for t in trades:
            p = t.get("profit", 0)
            total_profit += p
            message_lines.append(f"• Entry: {t['entry']} | TP: {t['tp']} | SL: {t['sl']} | PnL: £{p:.2f}")
        message_lines.append(f"💰 {symbol} Total PnL: £{total_profit:.2f}")
        await send_daily_chart(symbol, last_prices[symbol], session)
    message = "\n".join(message_lines)
    await send_telegram_alert(message, session)


async def check_closed_trades(session):
    global seen_closed_trades
    url = f"{OANDA_API_URL}/accounts/{ACCOUNT_ID}/transactions"
    params = {"type": "ORDER_FILL"}
    while True:
        try:
            async with session.get(url, headers=HEADERS, params=params) as resp:
                data = await resp.json()
                for tx in data.get("transactions", []):
                    trade_id = tx.get("tradeID")
                    if trade_id and trade_id not in seen_closed_trades:
                        realized_pl = float(tx.get("pl", 0))
                        balance = float(tx.get("accountBalance", 0))
                        seen_closed_trades.add(trade_id)
                        await send_telegram_alert(
                            f"📉 Trade Closed\n💰 Realized PnL: £{realized_pl:.2f}\n📊 Balance: £{balance:.2f}",
                            session
                        )
        except Exception as e:
            print(f"⚠️ Error checking closed trades: {e}")
        await asyncio.sleep(10)


async def main():
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            keep_stream_alive(session),
            check_closed_trades(session)
        )

if __name__ == "__main__":
    print(f"🚀 Starting multi-currency trading bot for: {', '.join(INSTRUMENTS)}")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Bot stopped by user")


