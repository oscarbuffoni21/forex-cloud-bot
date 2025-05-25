import pandas as pd

# Load all results
df = pd.read_csv("optimizer_results.csv")

# Filter for meaningful results
filtered = df[(df["TotalTrades"] >= 30) & (df["Profit"] > 0)]

# Sort by Profit and WinRate
best = filtered.sort_values(by=["Profit", "WinRate"], ascending=False).head(1)

# Save to file
with open("best_strategy_config.txt", "w") as f:
    for col in best.columns:
        f.write(f"{col} = {best.iloc[0][col]}\n")

print("✅ Re-saved best strategy to best_strategy_config.txt")
