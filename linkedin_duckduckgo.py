import json
import re
import time
import sys
from pathlib import Path

import pandas as pd
from duckduckgo_search import DDGS
from rapidfuzz import fuzz

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ============================================================
# CONFIG
# ============================================================
INPUT_FILE = "contacts_with_linkedin.xlsx"
OUTPUT_FILE = "contacts_with_linkedin.xlsx"
CHECKPOINT_EVERY = 25  # Save progress every N rows
SLEEP_BETWEEN = 2.0    # seconds between searches to avoid getting blocked by DDG

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
    if score >= 65: return "high"
    if score >= 40: return "medium"
    return "low"

# ============================================================
# DUCKDUCKGO SEARCH
# ============================================================
def duckduckgo_search(query, max_results=5):
    """Search using the free duckduckgo-search library"""
    try:
        results = []
        with DDGS() as ddgs:
            # text() returns an iterator of dicts: {'title': ..., 'href': ..., 'body': ...}
            for i, r in enumerate(ddgs.text(query, max_results=max_results)):
                results.append({
                    "link": r.get("href", ""),
                    "title": r.get("title", ""),
                    "snippet": r.get("body", "")
                })
        return results, None
    except Exception as e:
        status_code = getattr(e, "status_code", "Unknown")
        return [], f"DDG_ERROR: {str(e)} (Status: {status_code})"


# ============================================================
# MAIN
# ============================================================
def main():
    print(f"📂 Loading {INPUT_FILE}...")
    try:
        df = pd.read_excel(INPUT_FILE)
    except Exception as e:
        print("❌ ERROR: Please close the Excel file before running.")
        return

    total_rows = len(df)
    
    # Identify NOT_FOUND rows in range 1100-1400
    rows_to_process = []
    for i in range(total_rows):
        status = str(df.iloc[i].get("Contact LinkedIn URL", "")).strip()
        if 1099 <= i <= 1400 and status == "NOT_FOUND":
            rows_to_process.append(i)

    if not rows_to_process:
        print("🎉 No more 'NOT_FOUND' rows left in this range!")
        return
    
    print(f"🎯 Found {len(rows_to_process)} NOT_FOUND rows in range 1100-1400 to process with DuckDuckGo...")

    found_count = 0
    error_count = 0
    
    # We will process in batches to avoid rate limits
    limit = min(200, len(rows_to_process)) # Let's do max 200 at a time
    print(f"⚡ Processing a batch of {limit} rows...\n")

    for count, idx in enumerate(rows_to_process[:limit]):
        name = str(df.iloc[idx].get("Contact Name", "")).strip()
        company = str(df.iloc[idx].get("Company name", "")).strip()
        
        # Broader query for better DDG matching
        query = f'"{name}" "{company}" linkedin profile'
        
        print(f"[{count+1}/{limit}] Searching DDG for 👉 {name} @ {company}", end=" ")
        
        results, error = duckduckgo_search(query, max_results=5)
        
        if error:
            if "Ratelimit" in error or "429" in error:
                print("\n🛑 DuckDuckGo Rate Limit / Captcha block hit. Pausing script.")
                print("   Wait a few minutes or change your IP (VPN) and try again.")
                break
            else:
                print(f"❌ Error: {error}")
                error_count += 1
                time.sleep(SLEEP_BETWEEN)
                continue

        best_score = 0
        best_url = None

        for res in results:
            link = res["link"]
            if "linkedin.com/in/" not in link.lower(): continue
            
            # Clean URL
            link = re.sub(r"\?.*$", "", link).rstrip("/")
            
            s = score_candidate(name, company, link, res["title"], res["snippet"])
            if s > best_score:
                best_score = s
                best_url = link

        # If a reasonably good match is found
        if best_url and best_score >= 15:
            df.at[idx, "Contact LinkedIn URL"] = best_url
            df.at[idx, "LinkedIn Score"] = best_score
            df.at[idx, "LinkedIn Confidence"] = confidence_label(best_score)
            print(f"→ ✅ FOUND! {best_url} (Score: {best_score})")
            found_count += 1
        else:
            print("→ ❌ Still NOT_FOUND")
            # We don't overwrite NOT_FOUND so it can be retried later if needed

        # Save checkpoint to not lose data
        if (count + 1) % CHECKPOINT_EVERY == 0:
            df.to_excel(OUTPUT_FILE, index=False)
            print("💾 Progress saved...")

        # Be respectful to DuckDuckGo to avoid instant bans
        time.sleep(SLEEP_BETWEEN)

    # Final save
    print(f"\n💾 Saving final Excel file (Found {found_count} new profiles)")
    df.to_excel(OUTPUT_FILE, index=False)
    
    print("\n✅ Done with this batch!")
    unprocessed = len(rows_to_process) - limit
    if unprocessed > 0:
        print(f"🚀 There are {unprocessed} rows left! Run the script again to continue.")

if __name__ == "__main__":
    main()
