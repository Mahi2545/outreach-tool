import json
import re
import time
import sys
import pandas as pd
import requests
from rapidfuzz import fuzz

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

SEARCHAPI_KEY = "HQajFWPwBWzUhcKkqaFcBkyC"
INPUT_FILE = "contacts_with_linkedin.xlsx"
OUTPUT_FILE = "contacts_with_linkedin.xlsx"

def normalize(text):
    return re.sub(r"\s+", " ", str(text)).strip().lower()

def slug_tokens(url):
    match = re.search(r"linkedin\.com/in/([^/?#]+)", url.lower())
    if not match: return []
    slug = match.group(1)
    slug = re.sub(r"-[0-9a-f]{6,}$", "", slug)
    return [t for t in re.split(r"[^a-z0-9]+", slug) if t and len(t) > 1]

def score_candidate(name, company, url, title, snippet):
    score = 0.0
    name_lower = normalize(name)
    company_lower = normalize(company)
    name_tokens = name_lower.split()
    slug_toks = slug_tokens(url)
    blob = f"{title} {snippet}".lower()

    if slug_toks and name_tokens:
        overlap = len(set(slug_toks) & set(name_tokens))
        score += overlap * 20
        score += fuzz.token_set_ratio(" ".join(slug_toks), " ".join(name_tokens)) * 0.3

    score += fuzz.token_set_ratio(name_lower, blob) * 0.15

    if company_lower and len(company_lower) > 2:
        company_tokens = company_lower.split()
        company_hits = sum(1 for t in company_tokens if t in blob)
        score += min(company_hits, 3) * 10
        score += fuzz.partial_ratio(company_lower, blob) * 0.1

    if "/in/" in url and "detail/" not in url and "overlay/" not in url:
        score += 5
    return float(round(score, 2))

def confidence_label(score):
    if score >= 70: return "high"
    if score >= 45: return "medium"
    return "low"

def searchapi_search(query):
    url = "https://www.searchapi.io/api/v1/search"
    params = {
        "engine": "google",
        "q": query,
        "api_key": SEARCHAPI_KEY,
        "num": 5
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            results = []
            for item in data.get("organic_results", []):
                results.append({
                    "link": item.get("link", ""),
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                })
            return results, None
        else:
            return [], f"HTTP_{r.status_code}: {r.text[:100]}"
    except Exception as e:
        return [], str(e)

def main():
    try:
        df = pd.read_excel(INPUT_FILE)
    except Exception as e:
        print("ERROR: Please close the Excel file before running.")
        return

    # Identify NOT_FOUND rows in range 1200-1400
    not_found_indices = []
    for i in range(len(df)):
        if 1199 <= i <= 1400 and str(df.iloc[i].get("Contact LinkedIn URL", "")).strip() == "NOT_FOUND":
            not_found_indices.append(i)

    print(f"Targeting {len(not_found_indices)} NOT_FOUND rows in range 1200-1400 using SearchAPI.io")
    
    # Cap at 100 to avoid burning un-available credits
    limit = min(100, len(not_found_indices))
    rows_to_run = not_found_indices[:limit]

    found_count = 0
    error_count = 0
    quota_hit = False

    for count, idx in enumerate(rows_to_run):
        name = str(df.iloc[idx].get("Contact Name", "")).strip()
        comp = str(df.iloc[idx].get("Company name", "")).strip()
        
        # Broader fallback query since exact "site:linkedin.com/in" failed previously
        query = f'"{name}" "{comp}" linkedin profile'
        
        print(f"[{count+1}/{limit}] Searching fallback for: {name} @ {comp}...")
        results, error = searchapi_search(query)
        
        if error:
            if "status': 401" in error or "status': 429" in error or "quota" in error.lower() or "403" in error:
                print("⚠️ SearchAPI.io Quota Exhausted or API Key Invalid.")
                quota_hit = True
                break
            else:
                print(f"❌ Error: {error}")
                error_count += 1
                continue
                
        best_url = None
        best_score = 0.0
        
        for res in results:
            link = res["link"]
            if "linkedin.com/in/" not in link.lower(): continue
            link = re.sub(r"\?.*$", "", link).rstrip("/")
            
            s = score_candidate(name, comp, link, res["title"], res["snippet"])
            if s > best_score:
                best_score = s
                best_url = link

        if best_url and best_score >= 15: # minimum confidence to save it
            df.at[idx, "Contact LinkedIn URL"] = best_url
            df.at[idx, "LinkedIn Score"] = best_score
            df.at[idx, "LinkedIn Confidence"] = confidence_label(best_score)
            print(f"✅ Found: {best_url} (Score {best_score})")
            found_count += 1
        else:
            print("❌ Still NOT_FOUND even with fallback query.")

        time.sleep(0.5)

    print("\n💾 Saving results...")
    df.to_excel(OUTPUT_FILE, index=False)
    
    urls = df['Contact LinkedIn URL'].fillna('')
    total_found = urls.str.startswith('http', na=False).sum()
    total_not_found = urls.eq('NOT_FOUND').sum()
    total_skipped = urls.eq('SKIP_NO_DATA').sum()
    total_error = urls.str.startswith('ERROR:').sum()
    total_unprocessed = len(df) - total_found - total_not_found - total_skipped - total_error
    
    print("\n" + "="*40)
    print("📈 FINAL STATUS UPDATE 📈")
    print("="*40)
    print(f"From this SearchApi.io run, we successfully rescued {found_count} profiles that were previously NOT_FOUND.")
    if quota_hit: print("⚠️ Stopped early because SearchApi.io 100-credit free limit was reached.")
    print("-" * 40)
    print(f"✅ Total LinkedIn Profiles Found:  {total_found}")
    print(f"❌ Still NOT_FOUND:              {total_not_found}")
    print(f"⚠️ Errors / Quota Drops:         {total_error}")
    print(f"⏭ Skipped (No Name/Company):    {total_skipped}")
    print(f"📄 Unprocessed / Empty Rows:     {total_unprocessed}")
    print("="*40)

if __name__ == "__main__":
    main()
