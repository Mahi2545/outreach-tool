import json
import time
import os
import sys
import pandas as pd
import requests

# Reconfigure stdout for utf-8 (Windows)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ============================================================
# CONFIG
# ============================================================
APOLLO_API_KEY = "p4QTfEHZeDnE3Sk67h4ETw"
FILE_PATH = "contacts_with_linkedin.xlsx"

MAX_CREDITS = 70  # Trying another set of credits
SLEEP_BETWEEN = 7.0 # Increased to be very wise 

# ============================================================
# APOLLO MATCH
# ============================================================
def apollo_match(name, company):
    url = "https://api.apollo.io/v1/people/match"
    
    # Split name into first and last
    parts = str(name).split()
    first_name = parts[0] if len(parts) > 0 else ""
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
    
    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "organization_name": company
    }
    
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": APOLLO_API_KEY
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            person = data.get("person", {})
            if person:
                linkedin_url = person.get("linkedin_url")
                # Apollo sometimes returns URLs like "linkedin.com/in/..." without protocol
                if linkedin_url and not linkedin_url.startswith("http"):
                    linkedin_url = "https://" + linkedin_url
                return linkedin_url, "high" if linkedin_url else "none"
            return None, "no_match"
        elif response.status_code == 429:
            retry_after = response.headers.get("X-RateLimit-Reset-After") or response.headers.get("Retry-After")
            print(f" (Wait: {retry_after}s)", end="")
            return "RATE_LIMIT", "error"
        else:
            print(f" (Error body: {response.text[:200]})", end="")
            return None, f"HTTP_{response.status_code}"
    except Exception as e:
        return None, str(e)

# ============================================================
# MAIN
# ============================================================
def main():
    if not os.path.exists(FILE_PATH):
        print(f"Error: {FILE_PATH} not found.")
        return

    df = pd.read_excel(FILE_PATH)
    
    # Target specifically NOTHING but NOT_FOUND in the range 1100-1400
    # To be "wise", we avoid anything already tried by other APIs (like NOT_FOUND_VIA_SERP) if possible, 
    # but the user said "from 1100-1400 rows only" so we'll target all NOT_FOUNDs there.
    target_mask = df['Contact LinkedIn URL'] == 'NOT_FOUND'
    target_indices = [idx for idx in df[target_mask].index.tolist() if 1099 <= idx <= 1400]
    
    print(f"Loaded {len(df)} total rows.")
    print(f"Identified {len(target_indices)} NOT_FOUND rows to try with Apollo in range 1100-1400.")
    
    # Respect the 65 credit limit
    to_process = target_indices[:MAX_CREDITS]
    print(f"Will process exactly {len(to_process)} rows (Credit limit: {MAX_CREDITS}).")

    found_count = 0
    error_count = 0
    
    for i, idx in enumerate(to_process):
        row = df.loc[idx]
        name = row['Contact Name']
        company = row['Company name']

        print(f"[{i+1}/{len(to_process)}] {name} @ {company}", end=" ... ")
        
        url, status = apollo_match(name, company)
        
        if status == "error":
            print("RATE LIMITED. Stopping.")
            break
        elif url and url != "RATE_LIMIT":
            print(f"FOUND: {url}")
            df.at[idx, "Contact LinkedIn URL"] = url
            df.at[idx, "LinkedIn Confidence"] = "apollo_match"
            df.at[idx, "LinkedIn Score"] = 1.0
            found_count += 1
        elif status in ["no_match", "none"]:
            print("No match in Apollo")
            # Mark so we don't try again or know it failed Apollo
            df.at[idx, "Contact LinkedIn URL"] = "NOT_FOUND_VIA_APOLLO"
        else:
            print(f"Error/Other: {status}")
            error_count += 1

        # Save progress every 10 rows
        if (i + 1) % 10 == 0:
            df.to_excel(FILE_PATH, index=False)
            print("Progress saved.")

        time.sleep(SLEEP_BETWEEN)

    # Final save
    df.to_excel(FILE_PATH, index=False)
    print(f"\nFinished. Recovered {found_count} profiles via Apollo.")
    print(f"Updated {FILE_PATH}")

if __name__ == "__main__":
    main()
