# Cursor / AI IDE Build Prompt — Lead Scoring & Outreach Report Pipeline
## Context for the developer reading this prompt

This prompt is ready to paste directly into Cursor, Windsurf, or any AI coding assistant. It is self-contained. All data field names are taken from the actual HubSpot export file (`NY_lead_sheet_.xlsx`). Do not paraphrase — give this to Cursor verbatim.

---

# FULL CURSOR PROMPT (paste everything below this line)

---

## Project: Lead Scoring & Boss Outreach Report — HubSpot Export Pipeline

### What you are building

A Python script (`score_leads.py`) that reads an Excel file exported from HubSpot (`NY_lead_sheet_.xlsx`), scores every company row against 6 weighted signals (max 100 points), buckets them into outreach tiers, and writes two output files:

1. `scored_leads.xlsx` — the original data plus 9 new columns: individual signal scores, total score, tier, recommended action, and talk track
2. `boss_report.xlsx` — a clean summary sorted by score descending, formatted for executive consumption, showing only the top 50 companies with a pre-written talk track per row

No external API calls are needed in the core script. Enrichment API integration is handled in a separate module (`enrich.py`) described later.

---

### Input file details

Filename: `NY_lead_sheet_.xlsx`
Sheet name: `Sheet1`
Total rows: ~360 companies
Columns (exact names, preserve case and spacing):

| Column name | Type | Notes |
|---|---|---|
| `Company Name` | string | Primary identifier |
| `Industry` | string | Values: `Financial Services`, `Investment Management`, `Banking`, `Insurance`, `Investment Banking`, `Capital Markets`, `International Trade and Development` |
| `Employees on LinkedIn` | string | e.g. "365", "2K+" — informational only |
| `Revenue Range` | string | Values: `$5M - $10M`, `$10M - $20M`, `$20M - $50M`, `$50M - $100M` |
| `About` | string | Company description — informational |
| `LinkedIn Sales Nav URL` | string | URL to LinkedIn Sales Navigator |
| `Hiring on LinkedIn` | string | Values: `Yes` or `No` |
| `Connections` | string | Values like `"1 connection"`, `"3 connections"`, or NaN |
| `Senior Leadership Hires` | string | Values like `"1 senior leadership hire"`, `"3 senior leadership hires"`, or NaN |
| `Strategic Priority` | string | Free text, company's apparent priority |
| `Signal 5 (Connection)` | string | Values: `"1st and 2nd degree Connection"`, `"2nd degree Connection"`, `"2nd and 3rd degree Connection"`, `"-"` |
| `Signal 6(Location)` | string | Values: `"India"`, `"US"`, `"US and South Africa"`, `"Canada, Us and Spain"`, etc. or `"-"` |
| `Fit` | string | Pre-existing analyst note — preserve as-is |

---

### Scoring logic (implement exactly as specified)

Maximum possible score = 100 points. Each signal is independent.

#### Signal 1 — Industry fit (25 points)

```python
FINSERV_INDUSTRIES = {
    "Financial Services",
    "Banking",
    "Insurance",
    "Investment Banking",
    "Capital Markets"
}
# Award 25 if row["Industry"] is in FINSERV_INDUSTRIES
# Award 10 if row["Industry"] == "Investment Management" (adjacent, not primary ICP)
# Award 0 otherwise
```

#### Signal 2 — Revenue in ICP range (20 points)

```python
ICP_REVENUE_RANGES = {
    "$5M - $10M",
    "$10M - $20M",
    "$20M - $50M",
    "$50M - $100M"
}
# Award 20 if row["Revenue Range"] is in ICP_REVENUE_RANGES
# All values in this dataset qualify — keep the check explicit for future-proofing
```

#### Signal 3 — Hiring AI-related roles on LinkedIn (20 points)

```python
# Award 20 if row["Hiring on LinkedIn"].strip().lower() == "yes"
# Award 0 if "No" or NaN
```

#### Signal 4 — Network connection degree (15 points)

```python
# Parse row["Signal 5 (Connection)"]
# Award 15 if the string contains "1st" (1st degree = warmest)
# Award 10 if string contains "2nd" but NOT "1st" (2nd degree only)
# Award 0 if "-" or NaN or "3rd" only
# Note: "1st and 2nd degree Connection" contains "1st" → award 15
# Note: "2nd and 3rd degree Connection" contains "2nd" but not "1st" → award 10
```

#### Signal 5 — CXO / decision-maker located in India (12 points)

```python
# Parse row["Signal 6(Location)"]
# Award 12 if the string (case-insensitive) contains "india"
# Award 0 otherwise or if "-" or NaN
```

#### Signal 6 — Senior leadership roles being hired (8 points)

```python
# Parse row["Senior Leadership Hires"]
# Award 8 if not NaN and string contains "senior leadership hire" (case-insensitive)
# Try to extract the number: "3 senior leadership hires" → number = 3
# If number >= 3, award 8 (full)
# If number == 2, award 6
# If number == 1, award 4
# If NaN or missing, award 0
```

#### Total score and tier bucketing

```python
def calculate_tier(total_score):
    if total_score >= 75:
        return "Tier 1 — Hot"
    elif total_score >= 50:
        return "Tier 2 — Warm"
    elif total_score >= 25:
        return "Tier 3 — Cold"
    else:
        return "Tier 4 — Disqualified"

def recommended_action(tier):
    actions = {
        "Tier 1 — Hot": "Prioritize this week — request warm intro or direct outreach within 48hrs",
        "Tier 2 — Warm": "Add to 2-touch nurture sequence — contact within 2 weeks",
        "Tier 3 — Cold": "Enrich further and add to monthly content drip",
        "Tier 4 — Disqualified": "Do not contact — revisit if signals change"
    }
    return actions[tier]
```

#### Talk track generation

```python
def generate_talk_track(row, tier):
    """
    Build a 1-2 sentence personalized opener based on which signals fired.
    Priority order: AI hiring > leadership hire > strategic priority > industry fit
    """
    parts = []

    if row["s3_score"] > 0 and row["s6_score"] > 0:
        parts.append(f"We noticed {row['Company Name']} is actively expanding its AI capabilities and building out leadership — exactly the growth stage where Kollect delivers outsized ROI.")
    elif row["s3_score"] > 0:
        parts.append(f"We saw {row['Company Name']} is hiring for AI-related roles — we work with {row['Industry']} firms at this exact inflection point.")
    elif row["s6_score"] > 0:
        parts.append(f"{row['Company Name']} is investing in senior leadership — new leaders typically reset vendor priorities in the first 90 days.")

    if row["s5_score"] > 0:
        parts.append("Given your India-based leadership team, we can offer local context and timezone-aligned support.")

    if not parts:
        parts.append(f"We work with {row['Industry']} companies in the {row['Revenue Range']} range on AI adoption strategy.")

    if tier == "Tier 1 — Hot" and row["s4_score"] >= 10:
        parts.append("Our mutual connection can provide a warm introduction if helpful.")

    return " ".join(parts)
```

---

### Output columns to add (in order)

After all original columns, append:

| New column | Description |
|---|---|
| `s1_industry` | Signal 1 score (0, 10, or 25) |
| `s2_revenue` | Signal 2 score (0 or 20) |
| `s3_ai_hiring` | Signal 3 score (0 or 20) |
| `s4_network` | Signal 4 score (0, 10, or 15) |
| `s5_india_cxo` | Signal 5 score (0 or 12) |
| `s6_leadership_hire` | Signal 6 score (0, 4, 6, or 8) |
| `Total Score` | Sum of all signals (0–100) |
| `Tier` | "Tier 1 — Hot", "Tier 2 — Warm", "Tier 3 — Cold", "Tier 4 — Disqualified" |
| `Recommended Action` | String from recommended_action() |
| `Talk Track` | String from generate_talk_track() |

---

### Output file 1: `scored_leads.xlsx`

- All original columns + 10 new columns above
- Sorted by `Total Score` descending
- Sheet name: `All Companies`
- Row color coding using openpyxl:
  - Tier 1 rows: light green fill (#C6EFCE)
  - Tier 2 rows: light yellow fill (#FFEB9C)
  - Tier 3 rows: light orange fill (#FFCC99)
  - Tier 4 rows: no fill / white
- Header row: bold, dark gray background (#404040), white text
- Column widths: auto-fit to content, max 60 chars for text columns
- Freeze the top row

### Output file 2: `boss_report.xlsx`

This is the boss-facing deliverable. Keep it clean and minimal.

Columns to include (in this order):
1. `Company Name`
2. `Industry`
3. `Revenue Range`
4. `Total Score`
5. `Tier`
6. `Hiring on LinkedIn`
7. `Signal 5 (Connection)` (rename header to "Network Degree")
8. `Signal 6(Location)` (rename header to "CXO Location")
9. `Senior Leadership Hires`
10. `Strategic Priority`
11. `Fit` (existing analyst note)
12. `Recommended Action`
13. `Talk Track`
14. `LinkedIn Sales Nav URL`

Filter: Include only Tier 1 and Tier 2 companies (score >= 50).
Sort: By `Total Score` descending.
Sheet name: `Outreach Priority`

Add a second sheet called `Score Summary` with:
- Total companies analyzed
- Count and % by tier
- Count of companies with AI hiring signal
- Count of companies with India CXO

Formatting:
- Tier 1 rows: green fill (#C6EFCE), bold company name
- Tier 2 rows: yellow fill (#FFEB9C)
- Header row: bold, navy background (#1F3864), white text
- `Talk Track` column: word-wrap enabled, row height auto
- `Total Score` column: center-aligned, bold
- Add a thick border below the header row

---

### Main script structure

```
score_leads.py          ← main script, run this
enrich.py               ← optional enrichment module (separate)
requirements.txt        ← pandas, openpyxl
README.md               ← setup and run instructions
```

Entry point in `score_leads.py`:

```python
if __name__ == "__main__":
    input_file = "NY_lead_sheet_.xlsx"
    df = load_and_score(input_file)
    write_scored_leads(df, "scored_leads.xlsx")
    write_boss_report(df, "boss_report.xlsx")
    print(f"Done. {len(df)} companies scored.")
    print(df["Tier"].value_counts().to_string())
```

---

### requirements.txt

```
pandas>=2.0.0
openpyxl>=3.1.0
```

No other dependencies needed for the core script.

---

### enrich.py — Enrichment module (implement as separate file, run independently)

This module is optional and adds live data to improve signal accuracy. It requires paid API accounts (see API section below).

```python
# enrich.py
# Run: python enrich.py --input NY_lead_sheet_.xlsx --output enriched.xlsx
# Requires: APOLLO_API_KEY and PHANTOMBUSTER_API_KEY in .env

import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
PHANTOMBUSTER_API_KEY = os.getenv("PHANTOMBUSTER_API_KEY")

def apollo_enrich_company(linkedin_url: str) -> dict:
    """
    Use Apollo.io /organizations/enrich endpoint to get:
    - CEO/CTO/CDO name and location
    - Employee count
    - Technologies used
    Returns dict with keys: cxo_name, cxo_location, cxo_title
    """
    # Extract domain from LinkedIn URL
    # POST to https://api.apollo.io/v1/organizations/enrich
    # Header: {"X-Api-Key": APOLLO_API_KEY}
    # Body: {"linkedin_url": linkedin_url}
    # Parse response["organization"]["primary_phone"]["source"] and person fields
    pass

def check_linkedin_ai_jobs(company_name: str) -> bool:
    """
    Use RapidAPI LinkedIn Jobs Search to check if company
    is posting for AI/ML/data roles.
    Search query: "{company_name} artificial intelligence machine learning"
    Returns True if >= 1 result found.
    """
    pass

def run_enrichment(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each row, call enrichment APIs and update:
    - Signal 5 (Connection): set based on Phantombuster network export
    - Signal 6(Location): set CXO location from Apollo
    - Hiring on LinkedIn: verify with live job search
    """
    pass
```

---

### API accounts and costs needed

#### Required for core script (free):
- **None.** The core `score_leads.py` runs entirely offline on the existing Excel data.

#### Required for enrichment module (`enrich.py`):

| Service | Purpose | Tier needed | Est. monthly cost | Sign-up URL |
|---|---|---|---|---|
| **Apollo.io** | CXO name, title, India location verification | Basic ($49/mo) or free tier (50 exports/mo) | $0–$49 | https://app.apollo.io/signup |
| **Phantombuster** | Export boss's LinkedIn 1st/2nd degree connections for network signal | Starter ($59/mo) | $59 | https://phantombuster.com/pricing |
| **RapidAPI — LinkedIn Jobs Search** | Live verification that company is hiring AI roles | Pay-per-use (~$0.01/call) | $5–$20 | https://rapidapi.com/search/linkedin-jobs |

#### Optional for advanced enrichment (Phase 2):

| Service | Purpose | Cost |
|---|---|---|
| **Clay.com** | No-code enrichment hub, wraps Apollo + LinkedIn natively | $149/mo |
| **Clearbit** | Company firmographic enrichment | $99/mo |
| **Bombora** | B2B intent data (is company researching AI vendors?) | $1,000+/mo — skip for MVP |

#### Recommended MVP spend:
Apollo free tier (50 lookups) + Phantombuster Starter ($59/mo) = **$59/month** to enrich a 360-row list twice per month. Core script is free.

---

### .env file template

```
APOLLO_API_KEY=your_key_here
PHANTOMBUSTER_API_KEY=your_key_here
RAPIDAPI_KEY=your_key_here
```

Never commit `.env` to Git. Add it to `.gitignore`.

---

### README.md content to generate

Include:
1. One-line description
2. Setup: `pip install -r requirements.txt`
3. Run core script: `python score_leads.py`
4. Run enrichment: `python enrich.py --input NY_lead_sheet_.xlsx`
5. Signal weight table
6. Tier definitions
7. Output file descriptions

---

### Exact field mapping from the sheet to signal variables

This is the most important section — map these exactly:

```python
# In load_and_score(df):

df["s1_industry"] = df["Industry"].apply(score_industry)
df["s2_revenue"]  = df["Revenue Range"].apply(score_revenue)
df["s3_ai_hiring"]= df["Hiring on LinkedIn"].apply(score_ai_hiring)
df["s4_network"]  = df["Signal 5 (Connection)"].apply(score_network)
df["s5_india_cxo"]= df["Signal 6(Location)"].apply(score_india)
df["s6_leadership_hire"] = df["Senior Leadership Hires"].apply(score_leadership)

df["Total Score"] = (
    df["s1_industry"] + df["s2_revenue"] + df["s3_ai_hiring"] +
    df["s4_network"] + df["s5_india_cxo"] + df["s6_leadership_hire"]
)
df["Tier"] = df["Total Score"].apply(calculate_tier)
df["Recommended Action"] = df["Tier"].apply(recommended_action)
df["Talk Track"] = df.apply(lambda row: generate_talk_track(row, row["Tier"]), axis=1)
```

Note: `Signal 5 (Connection)` has a space before the parenthesis.
Note: `Signal 6(Location)` has NO space before the parenthesis.
These are different column names. Use them exactly.

---

### Edge cases to handle

- NaN in any signal column → treat as 0 / not present
- `"2K+"` in `Employees on LinkedIn` → do not score, informational only
- `"-"` in `Signal 5 (Connection)` or `Signal 6(Location)` → score 0, treat as missing
- Mixed case in `Signal 6(Location)` (e.g. `"Us, Israel"`) → lowercase before matching "india"
- `Hiring on LinkedIn` may have leading/trailing whitespace → strip before comparing

---

### Testing

After generating the files, verify:
1. Total score for row 0 (Global Association of Risk Professionals / GARP) should be:
   - s1: 25 (Financial Services)
   - s2: 20 ($20M - $50M)
   - s3: 0 (Hiring = No)
   - s4: 10 (2nd degree only)
   - s5: 0 (US, not India)
   - s6: 6 (2 senior leadership hires)
   - Total: **61** → Tier 2 — Warm

2. Row 3 (Solytics Partners) should be:
   - s1: 25 (Financial Services)
   - s2: 20 ($20M - $50M)
   - s3: 20 (Yes)
   - s4: 10 (2nd degree)
   - s5: 12 (India)
   - s6: 4 (1 senior leadership hire)
   - Total: **91** → Tier 1 — Hot

Print these two rows' scores to stdout as a sanity check before writing files.

---

# END OF CURSOR PROMPT
