import pandas as pd

# Load the file
df = pd.read_csv("trades.csv")

# Print original column names for debugging
print("Before:", df.columns.tolist())

# Strip spaces, lowercase all column names
df.columns = [col.strip().lower().replace(" ", "_") for col in df.columns]

# Ensure 'time' column exists (try to infer from similar names)
for possible in ["timestamp", "date", "datetime"]:
    if possible in df.columns and "time" not in df.columns:
        df.rename(columns={possible: "time"}, inplace=True)

# Fill missing 'outcome' column if needed
if "outcome" not in df.columns and "profit" in df.columns:
    df["outcome"] = df["profit"].apply(lambda x: "WIN" if x > 0 else "LOSS")

# Save the cleaned version (overwrite original)
df.to_csv("trades.csv", index=False)

# Print cleaned column names
print("✅ Cleaned columns:", df.columns.tolist())