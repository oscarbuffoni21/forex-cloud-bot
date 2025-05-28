from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import pandas as pd

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def read_trades():
    try:
     df = pd.read_csv("trades.csv").sort_values(by="time", ascending=False)
     table = df.to_html(index=False, classes="data", border=1)
    except Exception as e:
        table = f"<p>Error reading trades.csv: {e}</p>"

    return f"""
    <html>
        <head>
            <title>Live Trades</title>
            <style>
                body {{ font-family: Arial; padding: 40px; }}
                .data {{ border-collapse: collapse; width: 100%; }}
                .data th, .data td {{ padding: 8px 12px; border: 1px solid #ddd; text-align: right; }}
                .data th {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h2>📈 Live Trades</h2>
            {table}
        </body>
    </html>
    """