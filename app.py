from flask import Flask, render_template, request
import pandas as pd
from multi_pair_backtest import run_backtest  # This must return trades and stats

app = Flask(__name__)

@app.route("/")
def dashboard():
    view = request.args.get("view", "live")

    # Example: pull live and backtest data
    trades, stats = run_backtest()
    backtest_data = [t.to_dict() for t in trades]

    try:
        live_data = pd.read_csv("live_trades.csv").to_dict(orient="records")
    except:
        live_data = []

    return render_template(
        "dashboard.html",
        view=view,
        backtest_data=backtest_data,
        live_data=live_data
    )

if __name__ == "__main__":
    app.run(debug=True)