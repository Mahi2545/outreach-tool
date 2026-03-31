import pandas as pd

df = pd.read_excel("Linkedin contacts KRTRVRS.xlsx")
print(f"Rows: {len(df)}")
print(f"Columns: {list(df.columns)}")
print()
print(df.head(3).to_string())
print()
print("--- Sample values ---")
for col in df.columns:
    print(f"  {col}: {df[col].dropna().head(2).tolist()}")
