# kreatorverse_lead_engine.py
# ═══════════════════════════════════════════════════════════════════════
# KREATORVERSE LEAD SCORING ENGINE — SINGLE FILE, PRODUCTION READY
# ═══════════════════════════════════════════════════════════════════════
#
# Usage:
#   python kreatorverse_lead_engine.py                  → Full run
#   python kreatorverse_lead_engine.py --test           → First 5 rows only
#   python kreatorverse_lead_engine.py --skip-enrich    → Score from cached enrichment
#
# Input:  input/leads.csv  (exported from HubSpot)
# Output: output/scored_leads_YYYYMMDD.csv
#         output/top40_shortlist_YYYYMMDD.csv
#         output/pitches_YYYYMMDD.csv
#         output/outreach_schedule_YYYYMMDD.csv
#
# APIs:   Coresignal (LinkedIn data) — key in .env
#         Google Custom Search (news/funding) — key in .env
#         NewsAPI (funding/strategic signals) — key in .env
#         OpenAI (optional, for AI pitches) — key in .env
#
# ═══════════════════════════════════════════════════════════════════════

import os
import sys
import csv
import json
import time
import logging
import argparse
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not installed. Reading env vars directly.")

try:
    import openai
    openai.api_key = os.getenv("OPENAI_API_KEY")
    HAS_OPENAI = bool(os.getenv("OPENAI_API_KEY"))
except ImportError:
    HAS_OPENAI = False


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

# ── File paths ──────────────────────────────────────────────────────
INPUT_FILE = "input/leads.csv"  # default; can be overridden by --input
OUTPUT_DIR = "output"
CACHE_DIR = "cache"
LOG_DIR = "logs"

# ── API Keys (from .env) ───────────────────────────────────────────
CORESIGNAL_API_KEY = os.getenv("CORESIGNAL_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", "")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ── Coresignal API base URL ────────────────────────────────────────
CORESIGNAL_BASE_URL = "https://api.coresignal.com/cdapi/v1"

# ── ICP Filters ────────────────────────────────────────────────────
TARGET_INDUSTRIES = [
    "financial services", "banking", "investment management",
    "fintech", "insurance technology", "capital markets",
    "payments", "lending", "wealth management", "regtech"
]

# ── Scoring: Hiring Signal (25 pts max) ───────────────────────────
HIRING_RELEVANT_KEYWORDS = [
    "data engineer", "machine learning", "ml engineer",
    "data scientist", "compliance engineer", "payments engineer",
    "platform engineer", "ai engineer", "blockchain engineer",
    "risk analyst", "quantitative developer", "quant",
    "data architect", "analytics engineer", "devops",
    "cloud engineer", "backend engineer", "infrastructure",
    "software engineer", "full stack", "security engineer"
]

# ── Scoring: Leadership Titles (20 pts max) ───────────────────────
LEADERSHIP_TITLE_KEYWORDS = [
    "chief", "ceo", "cto", "cfo", "coo", "cro", "cdo", "cio", "ciso",
    "vp", "vice president", "svp", "senior vice president", "evp",
    "director", "managing director", "head of", "general manager",
    "partner", "managing partner", "principal"
]

# ── Scoring: Strategic Priority Keywords (10 pts max) ─────────────
STRATEGIC_KEYWORDS = [
    "artificial intelligence", "ai", "machine learning", "ml",
    "digital transformation", "data-driven", "cloud migration",
    "automation", "blockchain", "real-time analytics",
    "expansion", "global expansion", "ipo", "acquisition",
    "modernization", "platform migration", "api-first"
]

# ── Scoring: Funding Keywords ─────────────────────────────────────
FUNDING_KEYWORDS = [
    "raised", "funding", "series a", "series b", "series c",
    "series d", "series e", "investment round", "venture capital",
    "growth equity", "bridge round", "seed round", "pre-seed",
    "ipo", "spac", "debt facility", "credit facility"
]

# ── Lead Tier Thresholds ──────────────────────────────────────────
HOT_THRESHOLD = 70
WARM_THRESHOLD = 40

# ── Urgent Outreach Rules ─────────────────────────────────────────
URGENT_MIN_SENIOR_HIRES = 3
URGENT_REQUIRES_FUNDING = False  # True = AND logic, False = OR logic

# ── Shortlist Size ────────────────────────────────────────────────
SHORTLIST_TOP_N = 40

# ── Outreach Sequences ───────────────────────────────────────────
HOT_SEQUENCE = [
    {"day": 1,  "channel": "email",    "action": "personalized_pitch"},
    {"day": 3,  "channel": "linkedin", "action": "connection_request"},
    {"day": 7,  "channel": "email",    "action": "followup_strategic"},
    {"day": 12, "channel": "linkedin", "action": "value_add_dm"},
    {"day": 18, "channel": "email",    "action": "breakup_email"},
]

WARM_SEQUENCE = [
    {"day": 1,  "channel": "email",    "action": "general_value_prop"},
    {"day": 10, "channel": "linkedin", "action": "engage_then_dm"},
    {"day": 20, "channel": "email",    "action": "re_engagement"},
    {"day": 35, "channel": "linkedin", "action": "share_content"},
]

# ── Company Info (for pitches) ────────────────────────────────────
OUR_COMPANY = "Kreatorverse"
OUR_VALUE_PROP = "AI-powered data infrastructure and engineering solutions"


# ═══════════════════════════════════════════════════════════════════════
# LOGGING SETUP
# ═══════════════════════════════════════════════════════════════════════

def setup_logging():
    """Configure logging to console and file."""
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"run_{timestamp}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file)
        ]
    )
    return logging.getLogger("kreatorverse")


# ═══════════════════════════════════════════════════════════════════════
# RATE LIMITER
# ═══════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Track API usage to avoid exceeding free tier limits."""

    def __init__(self):
        self.usage = defaultdict(int)
        self.limits = {
            "coresignal": 1000,     # Adjust based on your plan
            "google_search": 95,    # Free tier: 100/day
            "newsapi": 95,          # Free tier: 100/day
            "openai": 200,          # Adjust based on tier
        }
        self.delays = {
            "coresignal": 1.0,      # 1 sec between calls
            "google_search": 1.5,
            "newsapi": 1.0,
            "openai": 1.0,
        }

    def can_call(self, service: str) -> bool:
        limit = self.limits.get(service, 1000)
        return self.usage[service] < limit

    def record(self, service: str):
        self.usage[service] += 1
        delay = self.delays.get(service, 1.0)
        time.sleep(delay)

    def remaining(self, service: str) -> int:
        limit = self.limits.get(service, 1000)
        return max(0, limit - self.usage[service])

    def summary(self) -> str:
        parts = []
        for svc, count in self.usage.items():
            limit = self.limits.get(svc, "?")
            parts.append(f"{svc}={count}/{limit}")
        return " | ".join(parts) if parts else "No API calls yet"


# Global rate limiter instance
rate_limiter = RateLimiter()


# ═══════════════════════════════════════════════════════════════════════
# CSV READER / WRITER
# ═══════════════════════════════════════════════════════════════════════

def read_leads_csv(file_path: str, last_n: int = None) -> List[Dict]:
    """
    Read the input CSV file.
    Handles various column name formats from HubSpot exports.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"Input file not found: {file_path}\n"
            f"Please place your HubSpot export at: {os.path.abspath(file_path)}"
        )

    companies = []

    with open(file_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        # Normalize column names (strip whitespace, lowercase)
        if reader.fieldnames:
            cleaned_fieldnames = [
                col.strip().lower().replace(" ", "_")
                for col in reader.fieldnames
            ]

        for row in reader:
            # Re-map to cleaned column names
            cleaned_row = {}
            for original_col, value in row.items():
                clean_col = original_col.strip().lower().replace(" ", "_")
                cleaned_row[clean_col] = (value or "").strip()

            # Map common HubSpot column variations to standard names
            company = {
                "name": _get_field(cleaned_row, [
                    "name", "company_name", "company", "companyname"
                ]),
                "domain": _get_field(cleaned_row, [
                    "domain", "company_domain", "website",
                    "company_domain_name", "website_url"
                ]),
                "industry": _get_field(cleaned_row, [
                    "industry", "company_industry", "sector"
                ]),
                "annual_revenue": _parse_revenue(_get_field(cleaned_row, [
                    "annual_revenue", "annualrevenue", "revenue",
                    "annual_revenue_(in_usd)", "estimated_revenue"
                ])),
                "employee_count": _parse_int(_get_field(cleaned_row, [
                    "number_of_employees", "numberofemployees",
                    "employees", "employee_count", "headcount",
                    "total_headcount", "num_employees"
                ])),
                "city": _get_field(cleaned_row, [
                    "city", "company_city"
                ]),
                "state": _get_field(cleaned_row, [
                    "state", "state/region", "state_region",
                    "company_state"
                ]),
                "linkedin_url": _get_field(cleaned_row, [
                    "linkedin_company_page", "linkedin_url",
                    "linkedin", "company_linkedin_url",
                    "linkedin_company_url"
                ]),
                "description": _get_field(cleaned_row, [
                    "description", "company_description", "about"
                ]),
                "hubspot_id": _get_field(cleaned_row, [
                    "record_id", "hubspot_id", "hs_object_id",
                    "company_id", "id"
                ]),
                "owner": _get_field(cleaned_row, [
                    "company_owner", "hubspot_owner", "owner",
                    "assigned_to"
                ]),
            }

            # Keep all original columns too (for pass-through)
            company["_original"] = cleaned_row

            companies.append(company)

    # If last_n specified, take last N rows
    if last_n and last_n < len(companies):
        companies = companies[-last_n:]

    return companies


def read_leads_file(file_path: str, last_n: int = None) -> List[Dict]:
    """
    Read leads from CSV or Excel and normalize into the schema expected by this engine.

    Expected normalized keys (subset):
    - name, domain, industry, annual_revenue, employee_count, city, state, linkedin_url, description
    """
    ext = Path(file_path).suffix.lower()
    if ext in (".csv",):
        return read_leads_csv(file_path, last_n=last_n)

    if ext in (".xlsx", ".xls"):
        if pd is None:
            raise RuntimeError(
                "pandas is required to read Excel files. Install dependencies with: "
                "python -m pip install -r requirements.txt"
            )
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Input file not found: {file_path}")

        df = pd.read_excel(file_path, dtype=str)
        # Normalize columns
        df.columns = [
            str(c).strip().lower().replace(" ", "_")
            for c in df.columns
        ]

        def pick(row: dict, keys: List[str]) -> str:
            for k in keys:
                v = (row.get(k) or "").strip()
                if v:
                    return v
            return ""

        companies: List[Dict] = []
        records = df.fillna("").to_dict(orient="records")
        for row in records:
            # Normalize row keys/values
            cleaned_row = {
                str(k).strip().lower().replace(" ", "_"): (str(v).strip() if v is not None else "")
                for k, v in row.items()
            }

            company = {
                "name": pick(cleaned_row, ["company_name", "name", "company", "account_name"]),
                "domain": pick(cleaned_row, ["domain", "company_domain", "website", "website_url", "company_domain_name"]),
                "industry": pick(cleaned_row, ["industry", "company_industry", "sector"]),
                "annual_revenue": _parse_revenue(pick(cleaned_row, ["annual_revenue", "annualrevenue", "revenue", "revenue_range", "estimated_revenue"])),
                "employee_count": _parse_int(pick(cleaned_row, ["number_of_employees", "employees", "employee_count", "headcount", "employees_on_linkedin"])),
                "city": pick(cleaned_row, ["city", "company_city"]),
                "state": pick(cleaned_row, ["state", "state/region", "state_region", "company_state"]),
                "linkedin_url": pick(cleaned_row, ["linkedin_company_page", "linkedin_url", "linkedin", "linkedin_sales_navigator_url", "linkedin_sales_nav_url"]),
                "description": pick(cleaned_row, ["description", "company_description", "about"]),
                "hubspot_id": pick(cleaned_row, ["record_id", "hubspot_id", "hs_object_id", "company_id", "id"]),
                "owner": pick(cleaned_row, ["company_owner", "hubspot_owner", "owner", "assigned_to"]),
                "_original": cleaned_row,
            }
            companies.append(company)

        if last_n and last_n < len(companies):
            companies = companies[-last_n:]

        return companies

    raise ValueError(f"Unsupported input file type: {ext} (expected .csv or .xlsx)")


def _get_field(row: dict, possible_keys: list) -> str:
    """Try multiple possible column names, return first match."""
    for key in possible_keys:
        val = row.get(key, "")
        if val:
            return val
    return ""


def _parse_revenue(value: str) -> float:
    """Parse revenue string to float. Handles $, M, K, commas."""
    if not value:
        return 0.0
    try:
        cleaned = value.replace("$", "").replace(",", "").strip()

        # Handle "50M", "50m"
        if cleaned.lower().endswith("m"):
            return float(cleaned[:-1]) * 1_000_000
        elif cleaned.lower().endswith("k"):
            return float(cleaned[:-1]) * 1_000
        elif cleaned.lower().endswith("b"):
            return float(cleaned[:-1]) * 1_000_000_000

        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def _parse_int(value: str) -> int:
    """Parse integer from string, handling commas and ranges."""
    if not value:
        return 0
    try:
        # Handle ranges like "100-500" → take midpoint
        if "-" in value and not value.startswith("-"):
            parts = value.split("-")
            low = float(parts[0].replace(",", "").strip())
            high = float(parts[1].replace(",", "").strip())
            return int((low + high) / 2)

        cleaned = value.replace(",", "").replace("+", "").strip()
        return int(float(cleaned))
    except (ValueError, TypeError):
        return 0


def write_csv(data: List[Dict], file_path: str):
    """Write list of dicts to CSV."""
    if not data:
        return

    Path(os.path.dirname(file_path)).mkdir(parents=True, exist_ok=True)

    # Exclude internal fields
    exclude_keys = {"_original"}
    fieldnames = [
        k for k in data[0].keys()
        if k not in exclude_keys
    ]

    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(data)


def write_insights_excel(
    scored: List[Dict],
    file_path: str,
    pitches: Optional[List[Dict]] = None,
    schedule: Optional[List[Dict]] = None,
):
    """
    Write a single-sheet Excel workbook with the key "insights" columns:
    where to reach (domain/linkedin/location) + why (signals + breakdown).
    """
    if pd is None:
        raise RuntimeError(
            "pandas is required to write Excel files. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        )
    if not scored:
        return

    def why_reach(row: Dict) -> str:
        parts: List[str] = []
        if row.get("funding_has_recent"):
            detail = (row.get("funding_latest_detail") or "").strip()
            parts.append(f"Funding: {detail[:100]}" if detail else "Funding: recent signals")
        if row.get("leadership_hire_count", 0):
            detail = (row.get("leadership_hires_detail") or "").strip()
            parts.append(f"Leadership hires: {detail[:120]}" if detail else "Leadership hires detected")
        if row.get("hiring_is_active"):
            roles = (row.get("hiring_relevant_roles") or "").strip()
            parts.append(f"Hiring: {roles[:120]}" if roles else "Hiring: ICP-relevant roles")
        if row.get("strategic_has_signal"):
            pri = (row.get("strategic_primary_priority") or "").strip()
            parts.append(f"Strategy: {pri}" if pri else "Strategy: signals found")
        if not parts:
            parts.append("Low external signals; baseline fit only")
        return " | ".join(parts)

    rows = []
    for r in scored:
        rows.append(
            {
                "rank": None,  # filled after sorting
                "company_name": r.get("name", ""),
                "tier": r.get("tier", ""),
                "lead_score": int(r.get("lead_score", 0) or 0),
                "is_urgent": bool(r.get("is_urgent", False)),
                "where_domain": r.get("domain", ""),
                "where_linkedin": r.get("linkedin_url", ""),
                "where_city": r.get("city", ""),
                "where_state": r.get("state", ""),
                "industry": r.get("industry", ""),
                "employee_count": r.get("employee_count", ""),
                "annual_revenue": r.get("annual_revenue", ""),
                "why_reach": why_reach(r),
                "score_breakdown": r.get("score_breakdown", ""),
                # Keep some raw signal fields for manager drill-down
                "hiring_relevant_count": r.get("hiring_relevant_count", 0),
                "hiring_total_open": r.get("hiring_total_open", 0),
                "funding_count": r.get("funding_count", 0),
                "strategic_primary_priority": r.get("strategic_primary_priority", ""),
                "leadership_hire_count": r.get("leadership_hire_count", 0),
            }
        )

    df = pd.DataFrame(rows)
    df = df.sort_values(by=["lead_score", "is_urgent"], ascending=[False, False]).reset_index(drop=True)
    df["rank"] = df.index + 1

    Path(os.path.dirname(file_path)).mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Insights")

        if pitches:
            pd.DataFrame(pitches).to_excel(writer, index=False, sheet_name="Pitches")
        if schedule:
            pd.DataFrame(schedule).to_excel(writer, index=False, sheet_name="Schedule")


# ═══════════════════════════════════════════════════════════════════════
# CORESIGNAL API CLIENT
# ═══════════════════════════════════════════════════════════════════════

class CoresignalClient:
    """
    Coresignal API client for LinkedIn data enrichment.
    
    Endpoints used:
    - POST /collect/search/filter — Search for companies
    - GET  /collect/companies/{id} — Get company details
    - POST /collect/jobs/search/filter — Search job listings
    - GET  /collect/members/search/filter — Search employees
    
    Docs: https://docs.coresignal.com/
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = CORESIGNAL_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self.enabled = bool(api_key)

        if not self.enabled:
            logging.getLogger("kreatorverse").warning(
                "Coresignal API key not found. LinkedIn enrichment disabled."
            )

    def _post(self, endpoint: str, payload: dict) -> Optional[dict]:
        """Make a POST request to Coresignal."""
        if not self.enabled:
            return None
        if not rate_limiter.can_call("coresignal"):
            logging.getLogger("kreatorverse").warning(
                "Coresignal rate limit reached"
            )
            return None

        url = f"{self.base_url}{endpoint}"

        try:
            response = requests.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=30
            )
            rate_limiter.record("coresignal")

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                logging.getLogger("kreatorverse").error(
                    "Coresignal: Invalid API key"
                )
                self.enabled = False
                return None
            elif response.status_code == 429:
                logging.getLogger("kreatorverse").warning(
                    "Coresignal: Rate limited. Waiting 30s..."
                )
                time.sleep(30)
                return None
            elif response.status_code == 404:
                return None
            else:
                logging.getLogger("kreatorverse").warning(
                    f"Coresignal {response.status_code}: "
                    f"{response.text[:200]}"
                )
                return None

        except requests.exceptions.Timeout:
            logging.getLogger("kreatorverse").warning(
                f"Coresignal timeout for {endpoint}"
            )
            return None
        except requests.exceptions.RequestException as e:
            logging.getLogger("kreatorverse").warning(
                f"Coresignal error: {e}"
            )
            return None

    def _get(self, endpoint: str) -> Optional[dict]:
        """Make a GET request to Coresignal."""
        if not self.enabled:
            return None
        if not rate_limiter.can_call("coresignal"):
            return None

        url = f"{self.base_url}{endpoint}"

        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=30
            )
            rate_limiter.record("coresignal")

            if response.status_code == 200:
                return response.json()
            else:
                return None

        except Exception as e:
            logging.getLogger("kreatorverse").warning(
                f"Coresignal GET error: {e}"
            )
            return None

    # ─── Company Search ─────────────────────────────────────
    def search_company(
        self,
        company_name: str,
        website: str = None
    ) -> Optional[dict]:
        """
        Search for a company on LinkedIn via Coresignal.
        Returns company data including ID for further lookups.
        """
        logger = logging.getLogger("kreatorverse")

        # Strategy 1: Search by website domain (most accurate)
        if website:
            domain = website.replace("https://", "").replace("http://", "")
            domain = domain.replace("www.", "").split("/")[0]

            payload = {
                "website": domain
            }
            result = self._post(
                "/collect/companies/search/filter",
                payload
            )
            if result:
                # Returns list of company IDs
                if isinstance(result, list) and len(result) > 0:
                    company_id = result[0]
                    return self._get(f"/collect/companies/{company_id}")
                elif isinstance(result, dict):
                    return result

        # Strategy 2: Search by company name
        payload = {
            "name": company_name
        }
        result = self._post(
            "/collect/companies/search/filter",
            payload
        )
        if result:
            if isinstance(result, list) and len(result) > 0:
                company_id = result[0]
                return self._get(f"/collect/companies/{company_id}")
            elif isinstance(result, dict):
                return result

        return None

    # ─── Job Listings Search ────────────────────────────────
    def search_jobs(
        self,
        company_name: str = None,
        company_linkedin_url: str = None,
        company_id: int = None
    ) -> List[dict]:
        """
        Search for active job listings at a company.
        Returns list of job postings.
        """
        logger = logging.getLogger("kreatorverse")

        # Build filter
        payload = {}
        if company_id:
            payload["company_id"] = company_id
        elif company_linkedin_url:
            payload["company_url"] = company_linkedin_url
        elif company_name:
            payload["company_name"] = company_name
        else:
            return []

        # Add date filter for recent jobs only (last 90 days)
        ninety_days_ago = (
            datetime.now() - timedelta(days=90)
        ).strftime("%Y-%m-%d")
        payload["created_at_gte"] = ninety_days_ago

        result = self._post(
            "/collect/jobs/search/filter",
            payload
        )

        if not result:
            return []

        # Result is either a list of job IDs or job objects
        jobs = []
        if isinstance(result, list):
            # It's a list of IDs — fetch each (limit to first 20)
            for job_id in result[:20]:
                if isinstance(job_id, (int, str)):
                    job_data = self._get(f"/collect/jobs/{job_id}")
                    if job_data:
                        jobs.append(job_data)
                elif isinstance(job_id, dict):
                    jobs.append(job_id)
        elif isinstance(result, dict):
            jobs = result.get("jobs", result.get("results", [result]))

        return jobs

    # ─── Employee / Member Search ───────────────────────────
    def search_employees(
        self,
        company_name: str = None,
        company_linkedin_url: str = None,
        company_id: int = None,
        title_filter: str = None
    ) -> List[dict]:
        """
        Search for employees at a company.
        Can filter by title to find leadership hires.
        """
        payload = {}
        if company_id:
            payload["company_id"] = company_id
        elif company_linkedin_url:
            payload["company_url"] = company_linkedin_url
        elif company_name:
            payload["company_name"] = company_name
        else:
            return []

        if title_filter:
            payload["title"] = title_filter

        # Look for people who started recently
        ninety_days_ago = (
            datetime.now() - timedelta(days=90)
        ).strftime("%Y-%m-%d")
        payload["member_experience_date_from_gte"] = ninety_days_ago

        result = self._post(
            "/collect/members/search/filter",
            payload
        )

        if not result:
            return []

        members = []
        if isinstance(result, list):
            for member_id in result[:30]:
                if isinstance(member_id, (int, str)):
                    member_data = self._get(
                        f"/collect/members/{member_id}"
                    )
                    if member_data:
                        members.append(member_data)
                elif isinstance(member_id, dict):
                    members.append(member_id)
        elif isinstance(result, dict):
            members = result.get("members", result.get("results", []))

        return members


# ═══════════════════════════════════════════════════════════════════════
# ENRICHMENT ENGINE
# ═══════════════════════════════════════════════════════════════════════

class EnrichmentEngine:
    """
    Multi-source enrichment:
    1. Coresignal → LinkedIn hiring, employees, leadership
    2. Google Search → Funding events, strategic signals
    3. NewsAPI → Press mentions, funding announcements
    """

    def __init__(self):
        self.coresignal = CoresignalClient(CORESIGNAL_API_KEY)
        self.logger = logging.getLogger("kreatorverse")

    def enrich_company(self, company: Dict) -> Dict:
        """
        Run all enrichment signals for one company.
        Returns enriched company dict.
        """
        name = company.get("name", "Unknown")
        domain = company.get("domain", "")
        linkedin_url = company.get("linkedin_url", "")
        revenue = company.get("annual_revenue", 0)

        self.logger.info(f"  Enriching: {name}")

        # ── 1. Coresignal: Company lookup ──
        cs_company = None
        cs_company_id = None

        if self.coresignal.enabled:
            cs_company = self.coresignal.search_company(name, domain)
            if cs_company:
                cs_company_id = cs_company.get("id")
                self.logger.info(
                    f"    ✓ Coresignal company found (ID: {cs_company_id})"
                )

        # ── 2. Hiring signals (Coresignal jobs) ──
        hiring_data = self._get_hiring_signals(
            name, linkedin_url, cs_company_id
        )

        # ── 3. Leadership hires (Coresignal members) ──
        leadership_data = self._get_leadership_signals(
            name, linkedin_url, cs_company_id
        )

        # ── 4. Funding events (Google + NewsAPI) ──
        funding_data = self._get_funding_signals(name, domain)

        # ── 5. Strategic priority signals (Google + NewsAPI) ──
        strategic_data = self._get_strategic_signals(name, domain)

        # ── 6. Revenue scoring ──
        revenue_data = self._score_revenue(revenue)

        # ── 7. Connection degree (placeholder — needs Sales Nav) ──
        connection_data = {
            "connection_degree": 3,
            "connection_score": 3
        }

        # If we have Coresignal data, try to infer employee count
        if cs_company and not company.get("employee_count"):
            company["employee_count"] = cs_company.get(
                "employees_count",
                cs_company.get("company_size", 0)
            )

        # ── Merge everything ──
        enriched = {
            **company,
            "enrichment_timestamp": datetime.now().isoformat(),

            # Coresignal company data
            "cs_company_id": cs_company_id or "",
            "cs_industry": (
                cs_company.get("industry", "") if cs_company else ""
            ),
            "cs_employee_count": (
                cs_company.get("employees_count", "")
                if cs_company else ""
            ),
            "cs_founded": (
                cs_company.get("founded", "") if cs_company else ""
            ),
            "cs_specialties": (
                str(cs_company.get("specialties", ""))[:200]
                if cs_company else ""
            ),

            # Hiring
            "hiring_is_active": hiring_data["is_active"],
            "hiring_relevant_count": hiring_data["relevant_count"],
            "hiring_relevant_roles": hiring_data["relevant_roles_str"],
            "hiring_total_open": hiring_data["total_open"],
            "hiring_score": hiring_data["score"],

            # Leadership
            "leadership_has_hires": leadership_data["has_hires"],
            "leadership_hire_count": leadership_data["hire_count"],
            "leadership_hires_detail": leadership_data["hires_detail"],
            "leadership_score": leadership_data["score"],

            # Funding
            "funding_has_recent": funding_data["has_funding"],
            "funding_count": funding_data["event_count"],
            "funding_latest_detail": funding_data["latest_detail"],
            "funding_score": funding_data["score"],

            # Strategic
            "strategic_has_signal": strategic_data["has_signal"],
            "strategic_primary_priority": strategic_data[
                "primary_priority"
            ],
            "strategic_details": strategic_data["details"],
            "strategic_score": strategic_data["score"],

            # Revenue
            "revenue_score": revenue_data["score"],
            "revenue_tier": revenue_data["tier"],

            # Connection
            "connection_degree": connection_data["connection_degree"],
            "connection_score": connection_data["connection_score"],
        }

        return enriched

    # ─── HIRING SIGNALS ─────────────────────────────────────
    def _get_hiring_signals(
        self,
        company_name: str,
        linkedin_url: str,
        cs_company_id: int = None
    ) -> Dict:
        """Get active job listings and check for ICP-relevant roles."""
        result = {
            "is_active": False,
            "relevant_count": 0,
            "relevant_roles_str": "",
            "total_open": 0,
            "score": 0
        }

        # Method 1: Coresignal job search
        if self.coresignal.enabled:
            jobs = self.coresignal.search_jobs(
                company_name=company_name,
                company_linkedin_url=linkedin_url,
                company_id=cs_company_id
            )

            if jobs:
                result["total_open"] = len(jobs)
                relevant_roles = []

                for job in jobs:
                    title = (
                        job.get("title", "") or
                        job.get("job_title", "") or
                        job.get("name", "")
                    ).lower()

                    is_relevant = any(
                        kw in title for kw in HIRING_RELEVANT_KEYWORDS
                    )
                    if is_relevant:
                        role_title = (
                            job.get("title", "") or
                            job.get("job_title", "") or
                            job.get("name", "Unknown Role")
                        )
                        relevant_roles.append(role_title)

                result["relevant_count"] = len(relevant_roles)
                result["relevant_roles_str"] = "; ".join(
                    relevant_roles[:5]
                )
                result["is_active"] = result["relevant_count"] > 0

                self.logger.info(
                    f"    Hiring: {result['total_open']} total, "
                    f"{result['relevant_count']} relevant"
                )

        # Method 2: Google Search fallback
        if not result["is_active"] and rate_limiter.can_call("google_search"):
            google_results = self._google_search(
                f'"{company_name}" hiring '
                f'("data engineer" OR "ML" OR "AI" OR "compliance") '
                f'site:linkedin.com/jobs OR site:greenhouse.io '
                f'OR site:lever.co OR site:ashbyhq.com',
                num_results=3,
                date_restrict="m3"
            )
            if google_results:
                result["is_active"] = True
                result["relevant_count"] = len(google_results)
                result["relevant_roles_str"] = "; ".join(
                    r.get("title", "")[:60] for r in google_results[:3]
                )

        # Score
        result["score"] = 25 if result["is_active"] else 0
        return result

    # ─── LEADERSHIP SIGNALS ─────────────────────────────────
    def _get_leadership_signals(
        self,
        company_name: str,
        linkedin_url: str,
        cs_company_id: int = None
    ) -> Dict:
        """Detect recent C-suite / VP / Director hires."""
        result = {
            "has_hires": False,
            "hire_count": 0,
            "hires_detail": "",
            "score": 0
        }

        leadership_hires = []

        # Method 1: Coresignal employee search
        if self.coresignal.enabled:
            # Search for senior titles at the company
            for title_query in ["Chief", "VP", "Director", "Head"]:
                members = self.coresignal.search_employees(
                    company_name=company_name,
                    company_linkedin_url=linkedin_url,
                    company_id=cs_company_id,
                    title_filter=title_query
                )

                for member in members:
                    member_name = (
                        member.get("name", "") or
                        member.get("full_name", "") or
                        f"{member.get('first_name', '')} "
                        f"{member.get('last_name', '')}"
                    ).strip()

                    member_title = (
                        member.get("title", "") or
                        member.get("headline", "")
                    )

                    # Check if title is actually senior
                    title_lower = member_title.lower()
                    is_senior = any(
                        kw.lower() in title_lower
                        for kw in LEADERSHIP_TITLE_KEYWORDS
                    )

                    if is_senior and member_name:
                        leadership_hires.append({
                            "name": member_name,
                            "title": member_title
                        })

                # Don't burn too many API calls per company
                if len(leadership_hires) >= 5:
                    break

        # Method 2: Google News fallback
        if not leadership_hires and rate_limiter.can_call("google_search"):
            google_results = self._google_search(
                f'"{company_name}" '
                f'("appointed" OR "hired" OR "joins" OR "named") '
                f'("CEO" OR "CTO" OR "CFO" OR "VP" OR "Director")',
                num_results=5,
                date_restrict="d90"
            )
            for gr in google_results:
                title = gr.get("title", "")
                snippet = gr.get("snippet", "")
                combined = f"{title} {snippet}"

                for kw in LEADERSHIP_TITLE_KEYWORDS[:10]:
                    if kw.lower() in combined.lower():
                        leadership_hires.append({
                            "name": "See source",
                            "title": title[:80],
                            "source": gr.get("link", "")
                        })
                        break

        # Deduplicate by name
        seen_names = set()
        unique_hires = []
        for hire in leadership_hires:
            name_key = hire.get("name", "").lower().strip()
            if name_key and name_key not in seen_names:
                seen_names.add(name_key)
                unique_hires.append(hire)

        result["hire_count"] = len(unique_hires)
        result["has_hires"] = result["hire_count"] > 0
        result["hires_detail"] = "; ".join(
            f"{h.get('name', '?')} ({h.get('title', '?')})"
            for h in unique_hires[:5]
        )

        # Score
        if result["hire_count"] >= 4:
            result["score"] = 20
        elif result["hire_count"] >= 2:
            result["score"] = 15
        elif result["hire_count"] == 1:
            result["score"] = 10
        else:
            result["score"] = 0

        self.logger.info(
            f"    Leadership: {result['hire_count']} senior hires found"
        )
        return result

    # ─── FUNDING SIGNALS ────────────────────────────────────
    def _get_funding_signals(
        self,
        company_name: str,
        domain: str
    ) -> Dict:
        """Search for recent funding events."""
        result = {
            "has_funding": False,
            "event_count": 0,
            "latest_detail": "",
            "score": 0
        }

        funding_mentions = []

        # Method 1: NewsAPI
        if NEWSAPI_KEY and rate_limiter.can_call("newsapi"):
            try:
                lookback = (
                    datetime.now() - timedelta(days=180)
                ).strftime("%Y-%m-%d")

                params = {
                    "q": (
                        f'"{company_name}" AND '
                        f'(funding OR raised OR series OR investment)'
                    ),
                    "from": lookback,
                    "language": "en",
                    "sortBy": "relevancy",
                    "pageSize": 10,
                    "apiKey": NEWSAPI_KEY
                }
                response = requests.get(
                    "https://newsapi.org/v2/everything",
                    params=params,
                    timeout=15
                )
                rate_limiter.record("newsapi")

                if response.status_code == 200:
                    articles = response.json().get("articles", [])
                    for article in articles:
                        title = (article.get("title") or "").lower()
                        desc = (
                            article.get("description") or ""
                        ).lower()
                        combined = f"{title} {desc}"

                        if any(kw in combined for kw in FUNDING_KEYWORDS):
                            funding_mentions.append({
                                "title": article.get("title", ""),
                                "date": article.get("publishedAt", ""),
                                "source": article.get(
                                    "source", {}
                                ).get("name", ""),
                                "url": article.get("url", "")
                            })

            except Exception as e:
                self.logger.warning(f"    NewsAPI error: {e}")

        # Method 2: Google Search fallback
        if not funding_mentions and rate_limiter.can_call("google_search"):
            google_results = self._google_search(
                f'"{company_name}" '
                f'("raised" OR "funding round" OR "series" '
                f'OR "investment")',
                num_results=5,
                date_restrict="m6"
            )
            for gr in google_results:
                title = gr.get("title", "").lower()
                snippet = gr.get("snippet", "").lower()
                combined = f"{title} {snippet}"

                if any(kw in combined for kw in FUNDING_KEYWORDS):
                    funding_mentions.append({
                        "title": gr.get("title", ""),
                        "url": gr.get("link", ""),
                        "snippet": gr.get("snippet", "")
                    })

        result["event_count"] = len(funding_mentions)
        result["has_funding"] = result["event_count"] > 0

        if funding_mentions:
            result["latest_detail"] = funding_mentions[0].get(
                "title", ""
            )[:150]

        # Score
        if result["event_count"] >= 2:
            result["score"] = 20
        elif result["event_count"] == 1:
            result["score"] = 15
        else:
            result["score"] = 0

        self.logger.info(
            f"    Funding: {result['event_count']} events found"
        )
        return result

    # ─── STRATEGIC SIGNALS ──────────────────────────────────
    def _get_strategic_signals(
        self,
        company_name: str,
        domain: str
    ) -> Dict:
        """Detect strategic priorities from news and social."""
        result = {
            "has_signal": False,
            "primary_priority": "",
            "details": "",
            "score": 0
        }

        keyword_counts = defaultdict(int)
        signal_sources = []

        # Google Search
        if rate_limiter.can_call("google_search"):
            google_results = self._google_search(
                f'"{company_name}" '
                f'("AI" OR "digital transformation" OR "expansion" '
                f'OR "machine learning" OR "automation" '
                f'OR "blockchain" OR "cloud" OR "modernization")',
                num_results=5,
                date_restrict="m6"
            )

            for gr in google_results:
                combined = (
                    f"{gr.get('title', '')} {gr.get('snippet', '')}"
                ).lower()

                for kw in STRATEGIC_KEYWORDS:
                    if kw.lower() in combined:
                        keyword_counts[kw] += 1
                        signal_sources.append({
                            "keyword": kw,
                            "source_title": gr.get("title", "")[:80]
                        })

        if keyword_counts:
            result["has_signal"] = True
            result["primary_priority"] = max(
                keyword_counts, key=keyword_counts.get
            )
            result["details"] = "; ".join(
                f"{s['keyword']}: {s['source_title']}"
                for s in signal_sources[:3]
            )
            result["score"] = 10

        self.logger.info(
            f"    Strategic: "
            f"{'Found -> ' + result['primary_priority'] if result['has_signal'] else 'None found'}"
        )
        return result

    # ─── REVENUE SCORING ────────────────────────────────────
    def _score_revenue(self, revenue: float) -> Dict:
        """Score based on revenue tier."""
        if not revenue or revenue == 0:
            return {"score": 5, "tier": "unknown"}

        if 50_000_000 <= revenue <= 100_000_000:
            return {"score": 15, "tier": "tier_1_preferred"}
        elif 20_000_000 <= revenue < 50_000_000:
            return {"score": 10, "tier": "tier_2"}
        elif 5_000_000 <= revenue < 20_000_000:
            return {"score": 5, "tier": "tier_3"}
        else:
            return {"score": 0, "tier": "out_of_range"}

    # ─── GOOGLE SEARCH HELPER ───────────────────────────────
    def _google_search(
        self,
        query: str,
        num_results: int = 5,
        date_restrict: str = None
    ) -> List[Dict]:
        """
        Google Custom Search API.
        Free: 100 queries/day.
        date_restrict: "d90" = 90 days, "m6" = 6 months, "y1" = 1 year
        """
        if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
            return []
        if not rate_limiter.can_call("google_search"):
            return []

        try:
            params = {
                "key": GOOGLE_API_KEY,
                "cx": GOOGLE_CSE_ID,
                "q": query,
                "num": min(num_results, 10)
            }
            if date_restrict:
                params["dateRestrict"] = date_restrict

            response = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
                timeout=15
            )
            rate_limiter.record("google_search")

            if response.status_code == 200:
                items = response.json().get("items", [])
                return [
                    {
                        "title": item.get("title", ""),
                        "link": item.get("link", ""),
                        "snippet": item.get("snippet", "")
                    }
                    for item in items
                ]
            else:
                return []

        except Exception as e:
            self.logger.warning(f"    Google Search error: {e}")
            return []


# ═══════════════════════════════════════════════════════════════════════
# SCORING ENGINE
# ═══════════════════════════════════════════════════════════════════════

class ScoringEngine:
    """Compute weighted lead scores and classify into tiers."""

    def __init__(self):
        self.logger = logging.getLogger("kreatorverse")

    def score_company(self, enriched: Dict) -> Dict:
        """Compute score for one enriched company."""
        hiring_score = enriched.get("hiring_score", 0)
        funding_score = enriched.get("funding_score", 0)
        leadership_score = enriched.get("leadership_score", 0)
        revenue_score = enriched.get("revenue_score", 0)
        connection_score = enriched.get("connection_score", 0)
        strategic_score = enriched.get("strategic_score", 0)

        total = (
            hiring_score +
            funding_score +
            leadership_score +
            revenue_score +
            connection_score +
            strategic_score
        )
        total = min(float(total), 100.0)
        total_int = int(round(total))

        # Tier
        if total_int >= HOT_THRESHOLD:
            tier = "HOT"
        elif total_int >= WARM_THRESHOLD:
            tier = "WARM"
        else:
            tier = "COLD"

        # Urgency
        is_urgent = False
        urgency_reasons = []

        lc = enriched.get("leadership_hire_count", 0)
        has_funding = enriched.get("funding_has_recent", False)

        if lc >= URGENT_MIN_SENIOR_HIRES:
            is_urgent = True
            urgency_reasons.append(f"{lc}+ senior hires")

        if has_funding:
            is_urgent = True
            urgency_reasons.append("Recent funding")

        # Score breakdown
        breakdown = (
            f"H:{hiring_score}/25 | "
            f"F:{funding_score}/20 | "
            f"L:{leadership_score}/20 | "
            f"R:{revenue_score}/15 | "
            f"C:{connection_score}/10 | "
            f"S:{strategic_score}/10 | "
            f"= {total_int}/100"
        )

        scored = {
            **enriched,
            "lead_score": total_int,
            "tier": tier,
            "is_urgent": is_urgent,
            "urgency_reasons": "; ".join(urgency_reasons),
            "score_breakdown": breakdown,
        }

        return scored

    def score_all(self, enriched_companies: List[Dict]) -> List[Dict]:
        """Score all and sort descending."""
        scored = []
        for company in enriched_companies:
            scored.append(self.score_company(company))

        scored.sort(key=lambda x: x["lead_score"], reverse=True)

        hot = sum(1 for c in scored if c["tier"] == "HOT")
        warm = sum(1 for c in scored if c["tier"] == "WARM")
        cold = sum(1 for c in scored if c["tier"] == "COLD")
        urgent = sum(1 for c in scored if c["is_urgent"])

        self.logger.info(
            f"  Scoring: HOT={hot} | WARM={warm} | COLD={cold} | URGENT={urgent}"
        )

        return scored

    def get_shortlist(
        self,
        scored: List[Dict],
        top_n: int = SHORTLIST_TOP_N
    ) -> List[Dict]:
        """Top N with connection degree priority."""
        def sort_key(c):
            score = c.get("lead_score", 0)
            conn = c.get("connection_degree", 3)
            conn_boost = {1: 5, 2: 3, 3: 0}.get(conn, 0)
            urgent_boost = 3 if c.get("is_urgent") else 0
            return score + conn_boost + urgent_boost

        sorted_list = sorted(scored, key=sort_key, reverse=True)
        return sorted_list[:top_n]


# ═══════════════════════════════════════════════════════════════════════
# PITCH GENERATOR
# ═══════════════════════════════════════════════════════════════════════

class PitchGenerator:
    """Generate personalized outreach pitches."""

    def __init__(self):
        self.logger = logging.getLogger("kreatorverse")

    def generate_pitch(self, company: Dict) -> Dict:
        """Generate pitch for one company (template-based, free)."""
        name = company.get("name", "your company")
        industry = company.get("industry", "financial services")
        priority = company.get("strategic_primary_priority", "")
        hiring_roles = company.get("hiring_relevant_roles", "")
        funding_detail = company.get("funding_latest_detail", "")
        hire_count = company.get("leadership_hire_count", 0)
        hires_detail = company.get("leadership_hires_detail", "")
        revenue = company.get("annual_revenue", 0)
        tier = company.get("tier", "WARM")

        # ── Pick strongest signal for opening ──
        signal_type = "general"
        opening = ""

        if funding_detail:
            signal_type = "funding"
            opening = (
                f"Congratulations on the recent funding round — "
                f"it's clear {name} is gearing up for a significant "
                f"growth phase."
            )
        elif hire_count >= 2:
            signal_type = "leadership"
            opening = (
                f"I noticed {name} has made {hire_count} senior "
                f"leadership hires recently — that kind of executive "
                f"buildout usually signals a strategic inflection."
            )
        elif hiring_roles:
            roles_preview = hiring_roles.split(";")[0].strip()
            signal_type = "hiring"
            opening = (
                f"I saw that {name} is actively hiring for roles "
                f"like {roles_preview} — that tells me you're "
                f"investing seriously in your tech capabilities."
            )
        elif priority:
            signal_type = "strategic"
            opening = (
                f"I've been following {name}'s focus on {priority} "
                f"— it's one of the most impactful strategic moves "
                f"in {industry} right now."
            )
        else:
            opening = (
                f"As a growing {industry} company in New York, "
                f"{name} is at the stage where data infrastructure "
                f"decisions shape the next growth chapter."
            )

        # ── Subject lines ──
        subjects = {
            "funding": f"{name}'s Next Chapter Needs Smarter Data",
            "leadership": f"{name}'s New Team + Better Infrastructure",
            "hiring": f"Re: {name}'s Data Engineering Buildout",
            "strategic": f"{name}'s {priority[:20]} Strategy — A Thought",
            "general": f"Data Infrastructure Idea for {name}"
        }
        subject = subjects.get(signal_type, f"Quick Thought for {name}")

        # ── Value prop ──
        value_props = {
            "funding": (
                f"At {OUR_COMPANY}, we help recently funded companies "
                f"build production-grade data infrastructure that "
                f"scales — not something you'll rip out in 18 months."
            ),
            "leadership": (
                f"New technical leaders often inherit data "
                f"infrastructure debt. {OUR_COMPANY} specializes "
                f"in helping companies audit, optimize, and "
                f"future-proof their data stack during transitions."
            ),
            "hiring": (
                f"Many companies we work with hired data engineers "
                f"first, then realized they needed the right "
                f"architecture foundation. {OUR_COMPANY} helps get "
                f"the foundation right so new hires are productive "
                f"from day one."
            ),
            "strategic": (
                f"{OUR_COMPANY} helps {industry} companies build "
                f"the data engineering foundations that make "
                f"{priority} initiatives succeed in production, "
                f"not just in POC."
            ),
            "general": (
                f"{OUR_COMPANY} works with {industry} companies "
                f"to build scalable, AI-ready data infrastructure "
                f"that drives real business outcomes."
            ),
        }
        value = value_props.get(signal_type, value_props["general"])

        # ── CTA ──
        cta = (
            f"Would a 40-minute conversation make sense to compare "
            f"notes on what we're seeing across the {industry} data "
            f"landscape? Happy to share benchmarks from companies "
            f"at a similar stage."
        )

        # ── Full email ──
        rev_display = self._format_revenue(revenue)
        email_body = (
            f"Hi [First Name],\n\n"
            f"{opening}\n\n"
            f"{value}\n\n"
            f"{cta}\n\n"
            f"Either way — excited to see what {name} builds next.\n\n"
            f"Best,\n"
            f"[Your Name]\n"
            f"{OUR_COMPANY}"
        )

        # ── LinkedIn connection note ──
        linkedin_note = (
            f"Hi [First Name] — been following {name}'s growth "
            f"in {industry}. We help similar companies with "
            f"{OUR_VALUE_PROP.lower()}. Would love to connect."
        )

        # ── Day 7 follow-up ──
        followup_ref = (
            f"a mention of {name} focusing on {priority}"
            if priority
            else f"{name} in the news recently"
        )
        followup_email = (
            f"Hi [First Name],\n\n"
            f"Following up on my note last week. I came across "
            f"{followup_ref} and it reinforced why I reached out.\n\n"
            f"We recently published a benchmarking report on data "
            f"infrastructure maturity across {industry} companies — "
            f"happy to share, no strings attached.\n\n"
            f"Would 30 minutes work this week or next?\n\n"
            f"Best,\n"
            f"[Your Name]\n"
            f"{OUR_COMPANY}"
        )

        # ── Day 12 LinkedIn DM ──
        linkedin_dm = (
            f"Hi [First Name] — thought you'd find this useful. "
            f"We just released our '{industry} Data Infrastructure "
            f"Benchmark Report' covering trends from 100+ companies "
            f"in your space. Happy to send it over. No pitch — "
            f"just useful data."
        )

        # ── Day 18 breakup ──
        breakup_email = (
            f"Hi [First Name],\n\n"
            f"I've reached out a couple times and don't want to be "
            f"a pest. If data infrastructure isn't a priority for "
            f"{name} right now, totally understand.\n\n"
            f"I'll leave you with our latest industry report — "
            f"no strings attached. If timing changes, I'm here.\n\n"
            f"Best,\n"
            f"[Your Name]\n"
            f"{OUR_COMPANY}"
        )

        return {
            "company_name": name,
            "tier": tier,
            "lead_score": company.get("lead_score", 0),
            "signal_type": signal_type,
            "subject_line": subject,
            "email_body_day1": email_body,
            "linkedin_note_day3": linkedin_note,
            "followup_email_day7": followup_email,
            "linkedin_dm_day12": linkedin_dm,
            "breakup_email_day18": breakup_email,
            "generated_at": datetime.now().isoformat()
        }

    def generate_ai_pitch(self, company: Dict) -> Dict:
        """Generate pitch using OpenAI (optional, costs ~$0.01)."""
        if not HAS_OPENAI:
            return self.generate_pitch(company)

        name = company.get("name", "the company")
        industry = company.get("industry", "financial services")
        priority = company.get("strategic_primary_priority", "growth")
        hiring = company.get("hiring_relevant_roles", "")
        funding = company.get("funding_latest_detail", "")
        hires = company.get("leadership_hire_count", 0)
        revenue = company.get("annual_revenue", "")

        prompt = f"""You are a B2B sales copywriter for {OUR_COMPANY}, 
which provides {OUR_VALUE_PROP}.

Write a personalized cold outreach EMAIL:

COMPANY: {name}
INDUSTRY: {industry}
REVENUE: ${self._format_revenue(revenue)}
STRATEGIC PRIORITY: {priority}
HIRING: {hiring}
RECENT FUNDING: {funding}
SENIOR HIRES (90 days): {hires}

RULES:
- Subject line: personalized, under 9 words
- Opening: reference ONE specific signal
- Value prop: connect our solution to their priority
- CTA: 40-minute intro call
- Tone: consultative, peer-to-peer
- Under 150 words

Format:
SUBJECT: [subject]
---
[email body]
---
LINKEDIN: [40-word connection note]"""

        try:
            if not rate_limiter.can_call("openai"):
                return self.generate_pitch(company)

            response = openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Expert B2B sales copywriter for "
                            "financial services technology."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=500
            )
            rate_limiter.record("openai")

            content = response.choices[0].message.content
            parts = content.split("---")

            subject = ""
            body = ""
            linkedin = ""

            for part in parts:
                part = part.strip()
                if "SUBJECT:" in part:
                    lines = part.split("\n")
                    for line in lines:
                        if line.strip().startswith("SUBJECT:"):
                            subject = line.replace(
                                "SUBJECT:", ""
                            ).strip()
                        else:
                            body += line + "\n"
                elif "LINKEDIN:" in part:
                    linkedin = part.replace("LINKEDIN:", "").strip()
                else:
                    body = part.strip()

            # Build result with AI content + template fallbacks
            template = self.generate_pitch(company)
            template["subject_line"] = subject or template["subject_line"]
            template["email_body_day1"] = body or template["email_body_day1"]
            template["linkedin_note_day3"] = (
                linkedin or template["linkedin_note_day3"]
            )
            template["signal_type"] = "ai_generated"
            return template

        except Exception as e:
            self.logger.warning(f"    OpenAI error: {e}")
            return self.generate_pitch(company)

    def generate_all(
        self,
        companies: List[Dict],
        use_ai: bool = False
    ) -> List[Dict]:
        """Generate pitches for all companies."""
        pitches = []
        for company in companies:
            tier = company.get("tier", "COLD")
            if tier == "HOT" and use_ai and HAS_OPENAI:
                pitch = self.generate_ai_pitch(company)
            else:
                pitch = self.generate_pitch(company)
            pitches.append(pitch)
        return pitches

    @staticmethod
    def _format_revenue(rev) -> str:
        try:
            rev = float(rev)
            if rev >= 1_000_000:
                return f"{rev / 1_000_000:.0f}M"
            elif rev >= 1_000:
                return f"{rev / 1_000:.0f}K"
            return str(int(rev))
        except (ValueError, TypeError):
            return "N/A"


# ═══════════════════════════════════════════════════════════════════════
# OUTREACH SCHEDULER
# ═══════════════════════════════════════════════════════════════════════

class OutreachScheduler:
    """Create day-by-day outreach schedule."""

    def __init__(self):
        self.logger = logging.getLogger("kreatorverse")

    def create_schedule(
        self,
        scored_companies: List[Dict],
        pitches: List[Dict],
        start_date: datetime = None
    ) -> List[Dict]:
        """Build the full outreach schedule."""
        if not start_date:
            start_date = datetime.now()

        # Pitch lookup
        pitch_map = {}
        for p in pitches:
            pitch_map[p["company_name"]] = p

        schedule = []

        for company in scored_companies:
            name = company.get("name", "Unknown")
            tier = company.get("tier", "COLD")
            score = company.get("lead_score", 0)
            urgent = company.get("is_urgent", False)
            pitch = pitch_map.get(name, {})

            if tier == "HOT":
                steps = HOT_SEQUENCE
            elif tier == "WARM":
                steps = WARM_SEQUENCE
            else:
                continue

            for step in steps:
                touch_date = start_date + timedelta(days=step["day"])

                content = self._get_content(
                    step["action"], pitch, company
                )

                schedule.append({
                    "company_name": name,
                    "tier": tier,
                    "lead_score": score,
                    "is_urgent": urgent,
                    "day": step["day"],
                    "date": touch_date.strftime("%Y-%m-%d"),
                    "channel": step["channel"],
                    "action": step["action"],
                    "content": content,
                    "status": "PENDING",
                })

        schedule.sort(key=lambda x: (x["date"], not x["is_urgent"], -x["lead_score"]))

        self.logger.info(
            f"  Schedule: {len(schedule)} touchpoints created"
        )
        return schedule

    def _get_content(
        self,
        action: str,
        pitch: Dict,
        company: Dict
    ) -> str:
        """Map action to content."""
        name = company.get("name", "")
        industry = company.get("industry", "financial services")

        mapping = {
            "personalized_pitch": pitch.get(
                "email_body_day1", ""
            ),
            "connection_request": pitch.get(
                "linkedin_note_day3", ""
            ),
            "followup_strategic": pitch.get(
                "followup_email_day7", ""
            ),
            "value_add_dm": pitch.get(
                "linkedin_dm_day12", ""
            ),
            "breakup_email": pitch.get(
                "breakup_email_day18", ""
            ),
            "general_value_prop": pitch.get(
                "email_body_day1", ""
            ),
            "engage_then_dm": (
                f"1. Like/comment on recent post from {name} "
                f"leadership\n"
                f"2. DM referencing the post"
            ),
            "re_engagement": (
                f"Hi [First Name],\n\n"
                f"Checking back in — we've published new research "
                f"on data infrastructure trends in {industry}.\n\n"
                f"Thought of {name}. Worth a quick chat?\n\n"
                f"Best,\n[Your Name]\n{OUR_COMPANY}"
            ),
            "share_content": (
                f"Share relevant content on LinkedIn related to "
                f"{name}'s industry"
            ),
        }

        return mapping.get(action, f"Execute: {action}")


# ═══════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════

def run_pipeline(
    test_mode: bool = False,
    skip_enrich: bool = False,
    input_file: str = INPUT_FILE,
    last_n: Optional[int] = None,
    outreach_outputs: bool = False,
):
    """
    Execute the complete pipeline:
    Read CSV → Enrich → Score → Shortlist → Pitch → Schedule
    """
    logger = setup_logging()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Ensure directories exist
    for d in [OUTPUT_DIR, CACHE_DIR, LOG_DIR, "input"]:
        Path(d).mkdir(parents=True, exist_ok=True)

    logger.info("=" * 65)
    logger.info("  KREATORVERSE LEAD SCORING ENGINE")
    logger.info("=" * 65)
    logger.info(f"  Input file: {input_file}")
    logger.info(f"  Test mode:  {test_mode}")
    logger.info(f"  Coresignal: {'Configured' if CORESIGNAL_API_KEY else 'Missing'}")
    logger.info(f"  Google CSE: {'Configured' if GOOGLE_API_KEY else 'Missing'}")
    logger.info(f"  NewsAPI:    {'Configured' if NEWSAPI_KEY else 'Missing'}")
    logger.info(f"  OpenAI:     {'Configured' if HAS_OPENAI else 'Missing (using templates)'}")
    logger.info(f"  Outreach outputs (pitches/schedule): {'ON' if outreach_outputs else 'OFF'}")
    logger.info("=" * 65)

    # ── STEP 1: Read input CSV ──────────────────────────────
    logger.info("\nSTEP 1: Reading lead data...")

    if last_n is None:
        last_n = 5 if test_mode else 20  # default behavior: last 20 rows
    companies = read_leads_file(input_file, last_n=last_n)

    logger.info(f"  Loaded {len(companies)} companies from {input_file}")

    if not companies:
        logger.error("No companies found in input file. Exiting.")
        return

    # Show what we loaded
    for i, c in enumerate(companies):
        logger.info(
            f"  [{i+1}] {c.get('name', '?'):30s} | "
            f"Rev: {PitchGenerator._format_revenue(c.get('annual_revenue', 0)):>6s} | "
            f"Emp: {c.get('employee_count', '?')}"
        )

    # ── STEP 2: Enrich ──────────────────────────────────────
    enriched_companies = []

    if skip_enrich:
        logger.info("\nSTEP 2: SKIPPED (--skip-enrich)")
        # Try to load from cache
        cache_files = sorted(Path(CACHE_DIR).glob("enriched_*.csv"))
        if cache_files:
            logger.info(f"  Loading from cache: {cache_files[-1]}")
            import csv as csv_module
            with open(cache_files[-1], "r", encoding="utf-8") as f:
                reader = csv_module.DictReader(f)
                for row in reader:
                    # Convert numeric fields back
                    for key in [
                        "annual_revenue", "employee_count",
                        "hiring_score", "funding_score",
                        "leadership_score", "revenue_score",
                        "connection_score", "strategic_score",
                        "hiring_relevant_count", "hiring_total_open",
                        "leadership_hire_count", "funding_count",
                        "connection_degree"
                    ]:
                        try:
                            row[key] = float(row.get(key, 0) or 0)
                        except (ValueError, TypeError):
                            row[key] = 0
                    for key in [
                        "hiring_is_active", "leadership_has_hires",
                        "funding_has_recent", "strategic_has_signal"
                    ]:
                        row[key] = str(row.get(key, "")).lower() == "true"
                    enriched_companies.append(row)
        else:
            logger.warning("  No cache found. Running enrichment...")
            skip_enrich = False

    if not skip_enrich:
        logger.info("\nSTEP 2: Enriching companies with live signals...")
        enricher = EnrichmentEngine()

        for i, company in enumerate(companies):
            logger.info(
                f"\n  [{i+1}/{len(companies)}] ----------------------"
            )
            enriched = enricher.enrich_company(company)
            enriched_companies.append(enriched)

            # Log API budget remaining
            if (i + 1) % 5 == 0:
                logger.info(
                    f"  API usage: {rate_limiter.summary()}"
                )

        # Cache enriched data
        cache_path = os.path.join(
            CACHE_DIR, f"enriched_{timestamp}.csv"
        )
        write_csv(enriched_companies, cache_path)
        logger.info(f"  Cached: {cache_path}")

    # ── STEP 3: Score & Classify ─────────────────────────────
    logger.info("\nSTEP 3: Scoring and classifying leads...")
    scorer = ScoringEngine()
    scored_companies = scorer.score_all(enriched_companies)

    # Single workbook output (manager-friendly)
    insights_path = os.path.join(OUTPUT_DIR, f"lead_insights_{timestamp}.xlsx")

    # Print all scored companies
    logger.info("\n  FULL SCORED LIST:")
    logger.info("  " + "-" * 75)
    logger.info(
        f"  {'#':>3s}  {'Score':>5s}  {'Tier':6s}  {'Urgent':7s}  "
        f"{'Company':<30s}  {'Breakdown'}"
    )
    logger.info("  " + "-" * 75)

    for i, c in enumerate(scored_companies):
        urgent_flag = "URGENT" if c.get("is_urgent") else ""
        logger.info(
            f"  {i+1:3d}  {int(c.get('lead_score', 0)):5d}  "
            f"{c.get('tier',''):6s}  "
            f"{urgent_flag:7s}  "
            f"{c.get('name', '?')[:30]:<30s}  "
            f"{c.get('score_breakdown', '')}"
        )

    # ── STEP 4: Shortlist ────────────────────────────────────
    logger.info(f"\nSTEP 4: Creating top {SHORTLIST_TOP_N} shortlist...")
    shortlist = scorer.get_shortlist(scored_companies, SHORTLIST_TOP_N)

    hot_leads = [c for c in shortlist if c["tier"] == "HOT"]
    warm_leads = [c for c in shortlist if c["tier"] == "WARM"]
    cold_leads = [c for c in shortlist if c["tier"] == "COLD"]
    urgent_leads = [c for c in shortlist if c.get("is_urgent")]

    logger.info(
        f"  Shortlist: {len(hot_leads)} HOT | "
        f"{len(warm_leads)} WARM | "
        f"{len(cold_leads)} COLD | "
        f"{len(urgent_leads)} URGENT"
    )

    all_pitches: List[Dict] = []
    schedule: List[Dict] = []

    if outreach_outputs:
        # ── STEP 5: Generate Pitches ─────────────────────────────
        logger.info("\nSTEP 5: Generating personalized pitches...")
        pitcher = PitchGenerator()

        # HOT leads get AI pitches (if available), WARM get templates
        hot_pitches = pitcher.generate_all(hot_leads, use_ai=HAS_OPENAI)
        warm_pitches = pitcher.generate_all(warm_leads, use_ai=False)
        all_pitches = hot_pitches + warm_pitches

        logger.info(f"  Generated {len(all_pitches)} pitches")

        # ── STEP 6: Outreach Schedule ────────────────────────────
        logger.info("\nSTEP 6: Building outreach schedule...")
        scheduler = OutreachScheduler()

        outreach_companies = [
            c for c in shortlist if c["tier"] in ("HOT", "WARM")
        ]
        schedule = scheduler.create_schedule(
            outreach_companies, all_pitches
        )

    else:
        logger.info("\nSTEP 5-6: Skipped outreach outputs (pitches/schedule).")

    # Write the single output workbook (no CSV outputs)
    write_insights_excel(
        scored_companies,
        insights_path,
        pitches=all_pitches if outreach_outputs else None,
        schedule=schedule if outreach_outputs else None,
    )
    logger.info(f"  Saved: {insights_path}")

    # ── FINAL SUMMARY ────────────────────────────────────────
    logger.info("\n" + "=" * 65)
    logger.info("  PIPELINE COMPLETE")
    logger.info("=" * 65)
    logger.info(f"  Companies processed:    {len(companies)}")
    logger.info(f"  Companies enriched:     {len(enriched_companies)}")
    logger.info(
        f"  Distribution:           "
        f"{len(hot_leads)} HOT | "
        f"{len(warm_leads)} WARM | "
        f"{len(cold_leads)} COLD"
    )
    logger.info(f"  Urgent outreach:        {len(urgent_leads)}")
    logger.info(f"  Pitches generated:      {len(all_pitches)}")
    logger.info(f"  Scheduled touchpoints:  {len(schedule)}")
    logger.info(f"  API usage:              {rate_limiter.summary()}")
    logger.info("\n  OUTPUT FILES:")
    logger.info(f"    {insights_path}")
    logger.info("=" * 65)

    return {
        "scored": scored_companies,
        "shortlist": shortlist,
        "insights_path": insights_path,
        "pitches": all_pitches if outreach_outputs else [],
        "schedule": schedule if outreach_outputs else [],
    }


# ═══════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Kreatorverse Lead Scoring Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python kreatorverse_lead_engine.py --input input/leads.csv            Full run (last 20 rows)
  python kreatorverse_lead_engine.py --input "NY lead sheet .xlsx"      Full run (last 20 rows)
  python kreatorverse_lead_engine.py --test          Test with 5 rows
  python kreatorverse_lead_engine.py --skip-enrich   Score from cached data
        """
    )
    parser.add_argument(
        "--input",
        default=INPUT_FILE,
        help="Path to leads file (.csv or .xlsx). Default: input/leads.csv",
    )
    parser.add_argument(
        "--last-n",
        type=int,
        default=None,
        help="Process only the last N rows (overrides defaults).",
    )
    parser.add_argument(
        "--outreach",
        action="store_true",
        help="Also generate pitches and an outreach schedule (optional).",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode: process only first 5 companies"
    )
    parser.add_argument(
        "--skip-enrich",
        action="store_true",
        help="Skip enrichment, score from last cached enrichment"
    )

    args = parser.parse_args()
    run_pipeline(
        test_mode=args.test,
        skip_enrich=args.skip_enrich,
        input_file=args.input,
        last_n=args.last_n,
        outreach_outputs=args.outreach,
    )