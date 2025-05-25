from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import pandas as pd
import os

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
def read_dashboard(request: Request):
    # === Load trades.csv ===
    try:
        trades_df = pd.read_csv("trades.csv")
        trades_df = trades_df.sort_values(by="time", ascending=False)
        net_profit = round(trades_df["profit"].sum(), 2)
        win_rate = round((trades_df[trades_df["profit"] > 0].shape[0] / trades_df.shape[0]) * 100, 2) if not trades_df.empty else 0.0
    except Exception as e:
        trades_df = pd.DataFrame()
        net_profit = 0.0
        win_rate = 0.0

    # === Load optimizer_results.csv and filter ===
    try:
        optimizer_df = pd.read_csv("optimizer_results.csv")
        filtered_optimizer = optimizer_df[
            (optimizer_df["TotalTrades"] >= 50) &
            (optimizer_df["Profit"] > 6.0)
        ]
        filtered_optimizer = filtered_optimizer.sort_values(by=["Profit", "WinRate"], ascending=False)
        opt_data = filtered_optimizer.to_dict(orient="records")
    except Exception as e:
        opt_data = []

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "data": trades_df.to_dict(orient="records"),
        "net_profit": net_profit,
        "win_rate": win_rate,
        "opt_data": opt_data
    })
