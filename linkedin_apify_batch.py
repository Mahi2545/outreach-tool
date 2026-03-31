import json
import re
from pathlib import Path

import pandas as pd
from apify_client import ApifyClient
from rapidfuzz import fuzz

# ============================================================
# CONFIG
# ============================================================
APIFY_TOKEN = "apify_api_Bng5NLg11Pjbzo6woQnbk0esfhRjVP3v3e6j"
INPUT_FILE = "contacts_with_linkedin.xlsx" # read from current progress
OUTPUT_FILE = "contacts_with_linkedin.xlsx"

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

    score += fuzz.token_set_ratio(name_lower, blob) * 0.15

    if company_lower and len(company_lower) > 2:
        company_tokens = company_lower.split()
        company_hits = sum(1 for t in company_tokens if t in blob)
        score += min(company_hits, 3) * 10
        score += fuzz.partial_ratio(company_lower, blob) * 0.1

    if "/in/" in url and "detail/" not in url and "overlay/" not in url:
        score += 5

    return round(score, 2)

def confidence_label(score):
    if score >= 70: return "high"
    if score >= 45: return "medium"
    return "low"

# ============================================================
# MAIN BATCH PROCESS
# ============================================================
def main():
    print(f"📂 Loading {INPUT_FILE}...")
    df = pd.read_excel(INPUT_FILE)
    total_rows = len(df)
    print(f"✅ Loaded {total_rows} rows")

    # 1. Identify rows to process
    rows_to_process = []
    
    for i in range(total_rows):
        row = df.iloc[i]
        existing = str(row.get("Contact LinkedIn URL", "")).strip()
        
        # Skip if already found, manually skipped
        if existing.startswith("http") or existing == "SKIP_NO_DATA":
            continue

        name = str(row.get("Contact Name", "")).strip()
        company = str(row.get("Company name", "")).strip()
        
        if not name or name == "nan" or not company or company == "nan":
            df.at[i, "Contact LinkedIn URL"] = "SKIP_NO_DATA"
            continue

        # Add to processing list - use fallback query if previously NOT_FOUND
        if existing == "NOT_FOUND":
            query = f'"{name}" "{company}" linkedin profile'
        else:
            query = f'site:linkedin.com/in "{name}" "{company}"'
            
        rows_to_process.append({"index": i, "name": name, "company": company, "query": query})

    if not rows_to_process:
        print("🎉 No unprocessed rows left! You are done.")
        df.to_excel(OUTPUT_FILE, index=False)
        return

    print(f"⚡ Found {len(rows_to_process)} unprocessed rows! Batching them into 1 single Apify run...")
    
    # Cap at 1000 for a single API call to avoid looping and use credits efficiently
    current_batch = rows_to_process[:1000]
    
    queries = "\n".join([r["query"] for r in current_batch])
    query_to_row = {r["query"]: r for r in current_batch}

    client = ApifyClient(APIFY_TOKEN)
    
    run_input = {
        "queries": queries,
        "maxPagesPerQuery": 1,
        "resultsPerPage": 6,
        "countryCode": "us"
    }
    
    print(f"⏳ Triggering Apify Actor (apify/google-search-scraper)... this takes ~2-4 minutes...")
    run = client.actor("apify/google-search-scraper").call(run_input=run_input)
    
    print(f"✅ Actor run complete! Processing results...")
    
    found_count = 0
    not_found_count = 0

    # 2. Match dataset items back to the DataFrame
    for item in client.dataset(run["defaultDatasetId"]).iterate_items():
        search_query = item.get("searchQuery", {}).get("term", "")
        organic_results = item.get("organicResults", [])
        
        if search_query not in query_to_row:
            continue
            
        row_data = query_to_row[search_query]
        idx = row_data["index"]
        name = row_data["name"]
        company = row_data["company"]
        
        best_url = None
        best_score = 0
        
        for res in organic_results:
            link = str(res.get("url", ""))
            if "linkedin.com/in/" not in link.lower():
                continue
                
            link = re.sub(r"\?.*$", "", link).rstrip("/")
            title = str(res.get("title", ""))
            snippet = str(res.get("description", ""))
            
            s = score_candidate(name, company, link, title, snippet)
            if s > best_score:
                best_score = s
                best_url = link
                
        if best_url:
            df.at[idx, "Contact LinkedIn URL"] = best_url
            df.at[idx, "LinkedIn Score"] = best_score
            df.at[idx, "LinkedIn Confidence"] = confidence_label(best_score)
            found_count += 1
            print(f"✅ [{idx+1}/{total_rows}] {name} @ {company} -> {best_url} (Score {best_score})")
        else:
            df.at[idx, "Contact LinkedIn URL"] = "NOT_FOUND"
            not_found_count += 1
            print(f"❌ [{idx+1}/{total_rows}] {name} @ {company} -> Not Found")

    # Save
    print(f"\n💾 Saving Excel file... (Found: {found_count}, Not Found: {not_found_count})")
    df.to_excel(OUTPUT_FILE, index=False)
    
    remaining = len(rows_to_process) - len(current_batch)
    if remaining > 0:
        print(f"🚀 NOTE: There are {remaining} rows left in the queue. Run this script again to process the next batch of 500!")

if __name__ == "__main__":
    main()
