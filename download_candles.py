import requests
import pandas as pd
from datetime import datetime, timedelta
import os
from tqdm import tqdm

# === CONFIG ===
API_KEY = "29311d57933f296890c32f56286ed54f-801350f3b7ce5aebe90fb3c8633d0e9d"
OANDA_URL = "https://api-fxpractice.oanda.com/v3"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}"
}
INSTRUMENTS = ["EUR_USD", "GBP_USD", "USD_JPY"]
GRANULARITY = "M15"
DAYS = 90

# === FETCH FUNCTION ===
def fetch_and_save_candles(symbol):
    print(f"📡 Fetching {symbol}...")
    end = datetime.utcnow()
    start = end - timedelta(days=DAYS)
    
    all_candles = []
    with tqdm(total=DAYS, desc=f"{symbol} progress", unit="day") as pbar:
        while start < end:
            url = f"{OANDA_URL}/instruments/{symbol}/candles"
            params = {
                "granularity": GRANULARITY,
                "price": "M",
                "from": start.isoformat("T") + "Z",
                "count": 5000
            }

            r = requests.get(url, headers=HEADERS, params=params)
            if r.status_code != 200:
                print(f"❌ Failed to fetch {symbol}: {r.status_code} {r.text}")
                break

            candles = r.json().get("candles", [])
            if not candles:
                print(f"⚠️ No more data for {symbol}")
                break

            all_candles.extend(candles)

            last_time = candles[-1]["time"]
            new_start = datetime.fromisoformat(last_time.replace("Z", ""))
            if new_start <= start:
                print(f"🛑 {symbol}: No further candles available (loop stalled).")
                break
            days_fetched = (new_start - start).days
            start = new_start
            pbar.update(days_fetched)

    if not all_candles:
        print(f"⚠️ No data collected for {symbol}")
        return

    data = []
    for c in all_candles:
        if c["complete"]:
            data.append({
                "time": c["time"],
                "open": float(c["mid"]["o"]),
                "high": float(c["mid"]["h"]),
                "low": float(c["mid"]["l"]),
                "close": float(c["mid"]["c"]),
                "volume": c["volume"]
            })

    df = pd.DataFrame(data)
    filename = f"{symbol}_15m.csv"
    df.to_csv(filename, index=False)
    print(f"✅ Saved to {filename}")

# === MAIN ===
if __name__ == "__main__":
    for symbol in tqdm(INSTRUMENTS, desc="Fetching pairs"):
        fetch_and_save_candles(symbol)