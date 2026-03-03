import pandas as pd
from pathlib import Path

summary_path = Path(r"C:\Users\NicholasSisco\OneDrive - Profound Medical\Documents\Analysis\20251118_Stanford\timing_summary_Stanford_064.csv")
df = pd.read_csv(summary_path)

# Make sure Treating is numeric
df["Treating"] = pd.to_numeric(df["Treating"], errors="coerce")

print("Describe Treating (all cases):")
print(df["Treating"].describe())

print("\nCases with Treating == 0:")
print(df.loc[df["Treating"] == 0, ["PtId","Treating"]])

print("\nCases with Treating < 1 minute:")
print(df.loc[(df["Treating"] < 1) & df["Treating"].notna(),
             ["Pt","PtId","Treating"]])
