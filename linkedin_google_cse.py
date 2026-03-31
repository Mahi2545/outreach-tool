"""
LinkedIn Profile Finder using Google Custom Search API
Finds exact LinkedIn profile URLs for contacts using Name + Company + City
"""

import json
import re
import time
import sys
from pathlib import Path

import pandas as pd
import requests
from rapidfuzz import fuzz

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ============================================================
# CONFIG
# ============================================================
GOOGLE_API_KEY = "AIzaSyCnTEgrX10hl0QzbENtRJ_a549P_vAtDLM"
GOOGLE_CX_ID = "96ab9fa3cfd514ac5"

INPUT_FILE = "contacts_with_linkedin.xlsx"
OUTPUT_FILE = "contacts_with_linkedin.xlsx"
CHECKPOINT_FILE = "contacts_with_linkedin.checkpoint.json"

CHECKPOINT_EVERY = 25  # Save progress every N rows
SLEEP_BETWEEN = 1.1    # seconds between API calls (stay under 100/day free tier)


# ============================================================
# HELPERS
# ============================================================
def normalize(text):
    """Normalize text for comparison"""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def slug_tokens(url):
    """Extract name tokens from a LinkedIn slug like /in/john-doe-123abc"""
    match = re.search(r"linkedin\.com/in/([^/?#]+)", url.lower())
    if not match:
        return []
    slug = match.group(1)
    # Remove trailing hex IDs (e.g., -2b3a4c5d)
    slug = re.sub(r"-[0-9a-f]{6,}$", "", slug)
    # Split on non-alphanumeric
    return [t for t in re.split(r"[^a-z0-9]+", slug) if t and len(t) > 1]


def score_candidate(name, company, url, title, snippet):
    """Score how well a search result matches the expected contact"""
    score = 0.0
    name_lower = normalize(name)
    company_lower = normalize(company)
    name_tokens = name_lower.split()
    slug_toks = slug_tokens(url)
    blob = f"{title} {snippet}".lower()

    # 1. Name tokens in slug (strongest signal)
    if slug_toks and name_tokens:
        overlap = len(set(slug_toks) & set(name_tokens))
        score += overlap * 20
        score += fuzz.token_set_ratio(" ".join(slug_toks), " ".join(name_tokens)) * 0.3

    # 2. Name in title/snippet
    name_ratio = fuzz.token_set_ratio(name_lower, blob)
    score += name_ratio * 0.15

    # 3. Company in title/snippet
    if company_lower and len(company_lower) > 2:
        company_tokens = company_lower.split()
        company_hits = sum(1 for t in company_tokens if t in blob)
        score += min(company_hits, 3) * 10
        company_ratio = fuzz.partial_ratio(company_lower, blob)
        score += company_ratio * 0.1

    # 4. Prefer clean profile URLs
    if "/in/" in url and "detail/" not in url and "overlay/" not in url:
        score += 5

    return round(score, 2)


def confidence_label(score):
    if score >= 70:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


# ============================================================
# GOOGLE CUSTOM SEARCH
# ============================================================
def google_cse_search(query, num_results=5):
    """Search using Google Custom Search JSON API"""
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CX_ID,
        "q": query,
        "num": min(num_results, 10),
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            results = []
            for item in data.get("items", []):
                results.append({
                    "link": item.get("link", ""),
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                })
            return results, None
        elif r.status_code == 429:
            return [], "RATE_LIMITED"
        elif r.status_code == 403:
            error_msg = r.json().get("error", {}).get("message", "")
            if "billing" in error_msg.lower() or "quota" in error_msg.lower():
                return [], f"QUOTA_EXCEEDED: {error_msg[:100]}"
            return [], f"FORBIDDEN: {error_msg[:100]}"
        else:
            return [], f"HTTP_{r.status_code}"
    except Exception as e:
        return [], str(e)


def find_linkedin_profile(name, company, city=""):
    """Search for a person's LinkedIn profile and return the best match"""
    
    # Build search query
    query = f'"{name}" "{company}" linkedin profile'
    if city and city.lower() not in ("nan", ""):
        query = f'"{name}" "{company}" "{city}"'

    results, error = google_cse_search(query, num_results=5)

    if error:
        return None, 0, error

    # Score all LinkedIn /in/ results
    best_url = None
    best_score = 0

    for item in results:
        link = item["link"]
        if "linkedin.com/in/" not in link.lower():
            continue

        # Normalize the URL
        link = re.sub(r"\?.*$", "", link)  # strip query params
        link = link.rstrip("/")

        s = score_candidate(name, company, link, item["title"], item["snippet"])
        if s > best_score:
            best_score = s
            best_url = link

    return best_url, best_score, None


# ============================================================
# CHECKPOINT
# ============================================================
def save_checkpoint(index):
    Path(CHECKPOINT_FILE).write_text(json.dumps({"last_index": index}), encoding="utf-8")


def load_checkpoint():
    p = Path(CHECKPOINT_FILE)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("last_index", -1)
        except Exception:
            pass
    return -1


# ============================================================
# MAIN
# ============================================================
def main():
    print(f"📂 Loading {INPUT_FILE}...")
    df = pd.read_excel(INPUT_FILE)
    total = len(df)
    print(f"✅ Loaded {total} rows")
    print(f"   Columns: {list(df.columns)}\n")

    # Add output columns
    for col in ["Contact LinkedIn URL", "LinkedIn Score", "LinkedIn Confidence"]:
        if col not in df.columns:
            df[col] = ""

    # Resume from checkpoint
    last_done = load_checkpoint()
    start = last_done + 1 if last_done >= 0 else 0
    if start > 0:
        print(f"🔄 Resuming from row {start} (checkpoint found)\n")

    # Select NOT_FOUND rows in range 1100-1400
    target_indices = []
    for i in range(len(df)):
        if 1099 <= i <= 1400 and str(df.iloc[i].get("Contact LinkedIn URL", "")).strip() == "NOT_FOUND":
            target_indices.append(i)

    print(f"Targeting {len(target_indices)} NOT_FOUND rows in range 1100-1400 using Google CSE")
    
    # Cap at 100 searches (Google CSE free limit)
    limit = min(100, len(target_indices))
    to_process = target_indices[:limit]

    found = 0
    skipped = 0
    errors = 0
    quota_hit = False

    for count, i in enumerate(to_process):
        row = df.iloc[i]

        # Skip if already has a LinkedIn URL
        existing = str(row.get("Contact LinkedIn URL", "")).strip()
        if existing.startswith("http"):
            skipped += 1
            continue

        name = str(row.get("Contact Name", "")).strip()
        company = str(row.get("Company name", "")).strip()
        city = str(row.get("City", "")).strip()

        # Skip rows with no name or company
        if not name or name == "nan" or not company or company == "nan":
            df.at[i, "Contact LinkedIn URL"] = "SKIP_NO_DATA"
            df.at[i, "LinkedIn Confidence"] = ""
            continue

        print(f"[{i+1}/{total}] {name} @ {company}", end=" → ")

        url, score, error = find_linkedin_profile(name, company, city)

        if error:
            if "QUOTA" in str(error) or "RATE" in str(error):
                print(f"⚠️ {error}")
                print("\n🛑 API quota/rate limit hit. Saving progress...")
                df.to_excel(OUTPUT_FILE, index=False)
                save_checkpoint(i - 1)
                quota_hit = True
                break
            else:
                print(f"ERROR: {error}")
                df.at[i, "Contact LinkedIn URL"] = f"ERROR: {error}"
                errors += 1
        elif url:
            print(f"✅ {url} (score: {score})")
            df.at[i, "Contact LinkedIn URL"] = url
            df.at[i, "LinkedIn Score"] = str(score)
            df.at[i, "LinkedIn Confidence"] = confidence_label(score)
            found += 1
        else:
            print("NOT_FOUND")
            df.at[i, "Contact LinkedIn URL"] = "NOT_FOUND"
            df.at[i, "LinkedIn Score"] = "0"
            df.at[i, "LinkedIn Confidence"] = "low"

        # Save checkpoint
        if (i + 1) % CHECKPOINT_EVERY == 0:
            df.to_excel(OUTPUT_FILE, index=False)
            save_checkpoint(i)
            print(f"\n💾 Progress saved ({i+1}/{total} rows processed)\n")

        time.sleep(SLEEP_BETWEEN)

    # Final save
    df.to_excel(OUTPUT_FILE, index=False)
    save_checkpoint(total - 1 if not quota_hit else i - 1)

    processed = i + 1 - start - skipped if not quota_hit else i - start - skipped
    print(f"\n{'='*50}")
    print(f"✅ Done! Results:")
    print(f"   Found:    {found} LinkedIn profiles")
    print(f"   Skipped:  {skipped} (already had URL)")
    print(f"   Errors:   {errors}")
    print(f"   📁 Saved: {OUTPUT_FILE}")
    if quota_hit:
        print(f"\n⚠️  Quota hit at row {i}. Run the script again to resume.")
        print(f"   It will automatically continue from where it stopped.")


if __name__ == "__main__":
    main()
