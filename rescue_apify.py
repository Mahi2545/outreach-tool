import re
import pandas as pd
from apify_client import ApifyClient
from rapidfuzz import fuzz

APIFY_TOKEN = "apify_api_vZtfD7mBnS8LgKWZ3lcncJYj7zUc8b079TMv"
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

def main():
    try:
        df = pd.read_excel(INPUT_FILE)
    except Exception as e:
        print("ERROR: Please close the Excel file before running.")
        return
        
    client = ApifyClient(APIFY_TOKEN)
    
    query_to_idx = {}
    for i in range(len(df)):
        name = str(df.iloc[i].get("Contact Name", "")).strip()
        comp = str(df.iloc[i].get("Company name", "")).strip()
        if name and comp and name != "nan" and comp != "nan":
            query = f'site:linkedin.com/in "{name}" "{comp}"'
            query_to_idx[query] = {"index": i, "name": name, "company": comp}
            
    found = 0
    not_found = 0
    
    run = client.run("PIfLoMoZi5L71LRPS").get()
    dataset_id = run["defaultDatasetId"]
    
    print(f"Fetching dataset {dataset_id} from the successful Apify run on the cloud...")
    for item in client.dataset(dataset_id).iterate_items():
        search_query = item.get("searchQuery", {}).get("term", "")
        organic_results = item.get("organicResults", [])
        
        if search_query not in query_to_idx: continue
            
        row_data = query_to_idx[search_query]
        idx = row_data["index"]
        
        existing = str(df.iloc[idx].get("Contact LinkedIn URL", "")).strip()
        if existing.startswith("http"): continue
            
        best_url = None
        best_score = 0.0
        for res in organic_results:
            link = str(res.get("url", ""))
            if "linkedin.com/in/" not in link.lower(): continue
            link = re.sub(r"\?.*$", "", link).rstrip("/")
            s = score_candidate(row_data["name"], row_data["company"], link, str(res.get("title", "")), str(res.get("description", "")))
            if s > best_score:
                best_score = s
                best_url = link
        
        if best_url:
            df.at[idx, "Contact LinkedIn URL"] = best_url
            df.at[idx, "LinkedIn Score"] = best_score
            df.at[idx, "LinkedIn Confidence"] = confidence_label(best_score)
            found += 1
        else:
            df.at[idx, "Contact LinkedIn URL"] = "NOT_FOUND"
            not_found += 1

    try:
        df.to_excel(OUTPUT_FILE, index=False)
        print(f"✅ SUCCESSFULLY SAVED! Rescued {found} profiles and identified {not_found} as NOT_FOUND.")
    except Exception as e:
        print(f"FAILED TO SAVE: {e}")

if __name__ == "__main__":
    main()
