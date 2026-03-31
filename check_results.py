import pandas as pd

df = pd.read_excel('contacts_with_linkedin.xlsx')
urls = df['Contact LinkedIn URL'].fillna('')

print('--- BREAKDOWN OF RESULTS ---')
print(f"Total Found Profiles (URL): {urls.str.startswith('http', na=False).sum()}")
print(f"NOT_FOUND: {urls.eq('NOT_FOUND').sum()}")
print(f"Skipped (No Name/Company): {urls.eq('SKIP_NO_DATA').sum()}")
print(f"Errors / Quota Hit: {urls.str.startswith('ERROR:').sum()}")
print(f"Unprocessed rows remaining: {len(df) - urls.str.startswith('http', na=False).sum() - urls.eq('NOT_FOUND').sum() - urls.eq('SKIP_NO_DATA').sum() - urls.str.startswith('ERROR:').sum()}")
