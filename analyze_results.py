import pandas as pd

df = pd.read_csv("optimizer_results.csv")

# Require at least 50 trades and >6% profit
filtered = df[(df["TotalTrades"] >= 50) & (df["Profit"] > 6.0)]

# Sort by profit and win rate
filtered = filtered.sort_values(by=["Profit", "WinRate"], ascending=False)

print(filtered.head(20))  # Show top 20