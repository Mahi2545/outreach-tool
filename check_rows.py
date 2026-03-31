import pandas as pd

df = pd.read_excel('contacts_with_linkedin.xlsx')
populated = df[df['Contact LinkedIn URL'].notna() & (df['Contact LinkedIn URL'] != '') & (df['Contact LinkedIn URL'] != 'SKIP_NO_DATA')]
print(f"Total profiles attempted (including NOT_FOUND / ERROR): {len(populated)}")

if not populated.empty:
    min_idx = populated.index.min()
    max_idx = populated.index.max()
    print(f"Searches happened from Row {min_idx + 1} to Row {max_idx + 1}")
    
found = populated[populated['Contact LinkedIn URL'].str.startswith('http', na=False)]
print(f"Total precise URLs actually found: {len(found)}")
