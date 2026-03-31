import json
import re
import time
import os
from pathlib import Path
import pandas as pd
import requests
from rapidfuzz import fuzz

# ============================================================
# CONFIG
# ============================================================
SERPAPI_KEY = "94e40dc012aa7fdeafef66d68ba1100cf4934bc94b7b9bc5f9e29703fe9ae2c4"
FILE_PATH = "contacts_with_linkedin.xlsx"
CHECKPOINT_FILE = "serpapi_not_found.checkpoint.json"

MAX_CREDITS = 250  # User said they have 250 credits
SLEEP_BETWEEN = 1.0 # seconds between API calls

# ============================================================
# HELPERS
# ============================================================
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

    name_ratio = fuzz.token_set_ratio(name_lower, blob)
    score += name_ratio * 0.15

    if company_lower and len(company_lower) > 2:
        company_tokens = company_lower.split()
        company_hits = sum(1 for t in company_tokens if t in blob)
        score += min(company_hits, 3) * 10
        company_ratio = fuzz.partial_ratio(company_lower, blob)
        score += company_ratio * 0.1

    if "/in/" in url and "detail/" not in url and "overlay/" not in url:
        score += 5
    return round(score, 2)

def confidence_label(score):
    if score >= 70: return "high"
    if score >= 45: return "medium"
    return "low"

# ============================================================
# SERPAPI
# ============================================================
def serpapi_search(query):
    url = "https://serpapi.com/search"
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": 5,
        "hl": "en",
        "gl": "us"
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

def find_linkedin_profile(name, company, city=""):
    # Single query to save credits as requested
    query = f'site:linkedin.com/in "{name}" "{company}"'
    if city and city.lower() not in ("nan", ""):
        # If city is very specific, might be too restrictive, but user asked not to waste.
        # We'll stick to name + company as it's most reliable for a single search.
        pass

    results, error = serpapi_search(query)
    if error or not results:
        # If site: search returns nothing, we won't waste another credit on a fallback 
        # unless it was a very specific query. 
        return None, 0, error

    best_url, best_score = None, 0
    for item in results:
        link = item["link"]
        if "linkedin.com/in/" not in link.lower(): continue
        link = re.sub(r"\?.*$", "", link).rstrip("/")
        s = score_candidate(name, company, link, item["title"], item["snippet"])
        if s > best_score:
            best_score = s
            best_url = link
    return best_url, best_score, None

# ============================================================
# MAIN
# ============================================================
def main():
    if not os.path.exists(FILE_PATH):
        print(f"Error: {FILE_PATH} not found.")
        return

    df = pd.read_excel(FILE_PATH)
    # Target NOT_FOUND only in range 1100-1400
    target_mask = df['Contact LinkedIn URL'] == 'NOT_FOUND'
    target_indices = [idx for idx in df[target_mask].index.tolist() if 1099 <= idx <= 1400]
    
    print(f"Loaded {len(df)} total rows.")
    print(f"Identified {len(target_indices)} rows to try with SerpApi in range 1100-1400.")
    
    limit = 50 # Try 50 to see if credits exist
    to_process = target_indices[:limit]
    print(f"Processing {len(to_process)} rows (Batch limit: {limit}).")

    found_count = 0
    error_count = 0
    
    for i, idx in enumerate(to_process):
        row = df.loc[idx]
        name = str(row.get("Contact Name", "")).strip()
        company = str(row.get("Company name", "")).strip()
        city = str(row.get("City", "")).strip()

        print(f"[{i+1}/{len(to_process)}] {name} @ {company}", end=" ... ")
        
        url, score, error = find_linkedin_profile(name, company, city)
        
        if error:
            print(f"ERROR: {error}")
            # Don't update URL to ERROR if user wants to retry later, 
            # maybe just keep NOT_FOUND or mark as ERROR_SERP
            df.at[idx, "Contact LinkedIn URL"] = f"SERP_ERROR"
            error_count += 1
            if "quota" in str(error).lower() or "402" in str(error):
                print("Quota limit reached.")
                break
        elif url and score >= 45: # Only accept decent matches
            print(f"FOUND: {url} ({score})")
            df.at[idx, "Contact LinkedIn URL"] = url
            df.at[idx, "LinkedIn Score"] = score
            df.at[idx, "LinkedIn Confidence"] = confidence_label(score)
            found_count += 1
        else:
            print("Still NOT_FOUND")
            # Keep it as NOT_FOUND or mark as SERP_NOT_FOUND to distinguish
            df.at[idx, "Contact LinkedIn URL"] = "NOT_FOUND_VIA_SERP"

        # Save progress every 10 rows
        if (i + 1) % 10 == 0:
            df.to_excel(FILE_PATH, index=False)
            print(f"Progress saved.")

        time.sleep(SLEEP_BETWEEN)

    # Final save
    df.to_excel(FILE_PATH, index=False)
    print(f"\nFinished. Found {found_count} profiles. Errors: {error_count}")
    print(f"Updated {FILE_PATH}")

if __name__ == "__main__":
    main()
