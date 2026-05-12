"""
Kreatorverse B2B FS prospect enrichment (bulk CSV/XLSX).

- Reads company rows (flexible column names).
- Adds segmentation, BIS/LQS, priority, pain hook, offering match, CXO placeholders,
  and strategic outreach fields (strategic fields fully populated when Priority >= 80).
- Does NOT overwrite non-empty cells for any generated column (leave existing research as-is).

Dependencies:
  pip install pandas openpyxl

Usage (PowerShell, from repo root):
  python "Lead scoring\\kreatorverse_fs_prospect_enricher.py" --input "path\\London_FS_Enriched_v2.xlsx"
  python "Lead scoring\\kreatorverse_fs_prospect_enricher.py" --input "data.csv" --output "out.csv" --sheet 0
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# ---------------------------------------------------------------------------
# Column detection (input)
# ---------------------------------------------------------------------------

NAME_ALIASES = (
    "company name",
    "company",
    "name",
    "organization",
    "account name",
)
COMPANY_LI_ALIASES = (
    "company linkedin url",
    "company linkedin",
    "linkedin url",
    "company_linkedin_url",
    "linkedin_company_url",
)
WEBSITE_ALIASES = (
    "company website",
    "website",
    "company_url",
    "domain",
)
REV_ALIASES = (
    "revenue range",
    "revenue",
    "annual revenue",
    "company revenue",
)
EMP_ALIASES = (
    "employee count",
    "employees",
    "company size",
    "headcount",
    "number of employees",
)
ABOUT_ALIASES = (
    "about company",
    "about",
    "description",
    "company description",
)
RECIPIENT_LI_ALIASES = (
    "recipient linkedin url",
    "recipient linkedin",
    "contact linkedin",
    "prospect linkedin",
)

# Output columns we may create or fill (normalized keys -> display names)
OUTPUT_SPECS: List[Tuple[str, str]] = [
    ("segmentation", "Segmentation"),
    ("segment_label", "Segment_Label"),
    ("bis", "Buying_Intent_Score_BIS"),
    ("lqs", "Lead_Quality_Score_LQS"),
    ("priority_score", "Priority_Score"),
    ("high_propensity", "High_Propensity_Buyer_Immediate_Outreach"),
    ("pain_hook", "Pain_Point_Hook"),
    ("offerings", "Best_Match_Kreatorverse_Offerings"),
    ("cxo_contacts", "Key_CxO_Contacts"),
    ("cxo_linkedin", "CxO_LinkedIn_URLs"),
    ("cxo_emails", "CxO_Email_IDs"),
    ("connection_type", "Connection_Type"),
    ("business_model", "Business_Model"),
    ("revenue_model", "Revenue_Model"),
    ("strategic_site", "Strategic_Site"),
    ("what_building", "What_They_Are_Building"),
    ("conversation_topic", "Conversation_Topic"),
    ("humanizing", "Humanizing_The_Conversation"),
    ("emotional_framework", "Emotional_Dual_Channel_Framework"),
]

# Also treat legacy / alternate headers as "already present" (do not overwrite)
OUTPUT_HEADER_ALIASES: Dict[str, Tuple[str, ...]] = {
    "segmentation": ("segment category", "company segment"),
    "segment_label": ("segment", "segmentation & segment label"),
    "bis": ("buying intent score", "bis", "buying intent"),
    "lqs": ("lead quality score", "lqs", "lead quality"),
    "priority_score": ("priority", "priority score (0-100)"),
    "high_propensity": ("high propensity", "high propensity buyer", "immediate outreach"),
    "pain_hook": ("pain point", "hook", "pain"),
    "offerings": ("kreatorverse", "best match", "offerings"),
    "cxo_contacts": ("cxo", "key contacts", "executive contacts"),
    "cxo_linkedin": ("cxo linkedin", "executive linkedin"),
    "cxo_emails": ("cxo email", "email id", "executive email"),
    "connection_type": ("connection type",),
    "business_model": ("business model",),
    "revenue_model": ("revenue model",),
    "strategic_site": ("strategic site",),
    "what_building": ("what they are building",),
    "conversation_topic": ("conversation topic",),
    "humanizing": ("humanizing the conversation",),
    "emotional_framework": ("emotional dual channel", "emotional framework"),
}


def _norm_header(h: Any) -> str:
    if h is None or (isinstance(h, float) and pd.isna(h)):
        return ""
    s = str(h).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    s = str(v).strip()
    return s == "" or s.lower() in {"nan", "none", "n/a", "na"}


def _find_column(df: pd.DataFrame, aliases: Tuple[str, ...]) -> Optional[str]:
    norm_map = {_norm_header(c): c for c in df.columns}
    for a in aliases:
        key = _norm_header(a)
        if key in norm_map:
            return norm_map[key]
    return None


def _build_reverse_alias_map() -> Dict[str, str]:
    """Maps any alias header (normalized) -> canonical output key."""
    m: Dict[str, str] = {}
    for key, display in OUTPUT_SPECS:
        m[_norm_header(display)] = key
        m[_norm_header(key)] = key
    for key, aliases in OUTPUT_HEADER_ALIASES.items():
        for a in aliases:
            m[_norm_header(a)] = key
    return m


REVERSE_ALIASES = _build_reverse_alias_map()


def _canonical_output_key_for_column(col: str) -> Optional[str]:
    return REVERSE_ALIASES.get(_norm_header(col))


def _parse_employee_mid(val: Any) -> float:
    if _blank(val):
        return 50.0
    s = str(val).lower().replace(",", "")
    m = re.search(r"(\d+)\s*[-–to]+\s*(\d+)", s)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2.0
    m = re.search(r"(\d+)\s*\+", s)
    if m:
        return float(m.group(1)) * 1.25
    m = re.search(r"(\d+)", s)
    if m:
        return float(m.group(1))
    return 50.0


def _revenue_tier_score(val: Any) -> int:
    if _blank(val):
        return 35
    s = str(val).lower()
    if any(x in s for x in ("billion", "bn", "100m", "500m", "250m")):
        return 85
    if any(x in s for x in ("50m", "75m", "100 m", "50 m")):
        return 75
    if any(x in s for x in ("10m", "25m", "20m", "30m", "40m")):
        return 65
    if any(x in s for x in ("1m", "2m", "5m", "under 10")):
        return 50
    if "startup" in s or "seed" in s:
        return 40
    return 45


SEGMENT_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("Lending & RegTech", ("lend", "loan", "credit", "mortgage", "fca", "regtech", "compliance", "kyc", "aml")),
    ("AI-Native FinTechs", ("ai ", " artificial intelligence", "llm", "machine learning", "genai", "agent", "nlp")),
    ("Platform & Payments", ("payment", "paytech", "psp", "acquiring", "card", "wallet", "rails", "open banking", "api platform")),
    ("Investment Mgmt & Wealth Tech", ("wealth", "asset management", "portfolio", "fund", "investment", "family office", "ria")),
    ("Banking & Core Infrastructure", ("bank", "core banking", "ledger", "treasury", "liquidity")),
    ("Insurance & InsurTech", ("insur", "underwriting", "claims", "policy", "actuarial")),
]


def _classify_segment(text: str) -> str:
    t = text.lower()
    scores: Dict[str, int] = {label: 0 for label, _ in SEGMENT_RULES}
    for label, kws in SEGMENT_RULES:
        scores[label] = sum(1 for k in kws if k in t)
    best = max(scores.values())
    if best == 0:
        return "Financial Services (General)"
    for label, _ in SEGMENT_RULES:
        if scores[label] == best:
            return label
    return "Financial Services (General)"


def _pain_from_text(text: str, segment: str) -> str:
    t = text.lower()
    if "consumer duty" in t or "consumer-duty" in t:
        return "FCA Consumer Duty evidence chain: outcomes testing, fair value, vulnerable customers — needs unified data and controlled workflows."
    if "basel" in t or "capital adequacy" in t:
        return "Regulatory capital / Basel-style reporting complexity — fragmented risk data and manual controls slowing attestation cycles."
    if any(x in t for x in ("silos", "fragment", "legacy", "multiple systems", "spreadsheet")):
        return "Data fragmentation across product and compliance stacks — high cost to ship analytics-grade reporting and AI safely."
    if any(x in t for x in ("scale", "growth", "expand", "international")):
        return "Operational scale without linear headcount — process entropy across onboarding, servicing, and controls."
    if "ai" in t or "automation" in t:
        return "Moving from pilots to governed AI in production — needs enterprise data foundations and agent guardrails."
    if "Lending" in segment:
        return "Credit lifecycle velocity vs. risk controls — model governance, portfolio monitoring, and explainable decisions at scale."
    if "Payments" in segment or "Platform" in segment:
        return "Reliability, fraud, and scheme change velocity — event data quality and operational runbooks under pressure."
    if "Wealth" in segment or "Investment" in segment:
        return "Client reporting, suitability, and portfolio analytics — consistent master data across channels and instruments."
    return "Modernization pressure: compliance evidence, faster product cycles, and trustworthy AI — constrained by legacy data and processes."


def _offerings_for_pain(pain: str, segment: str) -> str:
    parts = [
        "Enterprise Data Re-engineering: canonical entities, lineage, and quality gates so risk/compliance and AI share one trusted layer.",
        "Business Process Re-engineering: orchestrate KYC/servicing/reporting workflows with measurable SLAs and audit trails.",
        "AI Agent Integration: retrieval-grounded copilots and operational agents with policy enforcement and human-in-the-loop.",
    ]
    if "fragment" in pain.lower() or "data" in pain.lower():
        parts[0] = "[Primary] " + parts[0]
    if "process" in pain.lower() or "workflow" in pain.lower() or "entropy" in pain.lower():
        parts[1] = "[Primary] " + parts[1]
    if "ai" in pain.lower() or "govern" in pain.lower() or "AI-Native" in segment:
        parts[2] = "[Primary] " + parts[2]
    return " | ".join(parts)


def _bis_lqs_priority(
    about: str,
    emp_mid: float,
    rev_score: int,
    segment: str,
) -> Tuple[int, int, int]:
    text = (about or "").lower()
    bis = 40
    lqs = 40
    # Buying intent proxies
    if any(k in text for k in ("hiring", "scale", "launch", "expand", "transform", "moderniz", "migrate", "platform")):
        bis += 12
    if any(k in text for k in ("ai", "machine learning", "automation", "digital")):
        bis += 10
    if emp_mid >= 500:
        bis += 15
    elif emp_mid >= 200:
        bis += 10
    elif emp_mid >= 50:
        bis += 5
    bis += max(0, min(20, (rev_score - 40) // 3))
    # Lead quality / ICP fit (FS + tech maturity hints)
    if segment != "Financial Services (General)":
        lqs += 15
    if any(k in text for k in ("api", "cloud", "data platform", "warehouse", "snowflake", "kubernetes")):
        lqs += 12
    if any(k in text for k in ("regulated", "fca", "compliance", "risk", "audit")):
        lqs += 8
    if emp_mid >= 100:
        lqs += 8
    lqs += max(0, min(15, (rev_score - 40) // 4))
    bis = int(max(0, min(100, bis)))
    lqs = int(max(0, min(100, lqs)))
    priority = int(round(0.55 * bis + 0.45 * lqs))
    priority = max(0, min(100, priority))
    return bis, lqs, priority


def _business_revenue_models(text: str) -> Tuple[str, str]:
    t = text.lower()
    bm = "B2B"
    if any(k in t for k in ("consumer", "retail customers", "cardholder", "individual investors")):
        bm = "B2B2C / Hybrid"
    rm = "Mixed / undisclosed"
    if any(k in t for k in ("subscription", "saas", "platform fee")):
        rm = "Subscription / platform fees"
    if any(k in t for k in ("interchange", "transaction", "payment volume", "aum", "assets under management")):
        rm = "Transaction- or volume-based / AUM-linked"
    return bm, rm


def enrich_row(row: pd.Series, colmap: Dict[str, str]) -> Dict[str, Any]:
    def g(key: str) -> Any:
        c = colmap.get(key)
        return row[c] if c and c in row.index else None

    name = g("name")
    company = str(name).strip() if not _blank(name) else "Unknown Company"
    about = str(g("about") or "")
    website = g("website")
    company_li = g("company_li")
    recipient_li = g("recipient_li")
    emp_mid = _parse_employee_mid(g("employees"))
    rev_score = _revenue_tier_score(g("revenue"))

    blob = f"{company} {about}"
    segment = _classify_segment(blob)
    pain = _pain_from_text(about, segment)
    offerings = _offerings_for_pain(pain, segment)
    bis, lqs, priority = _bis_lqs_priority(about, emp_mid, rev_score, segment)
    high = "Yes" if priority >= 80 else "No"

    site = str(website).strip() if not _blank(website) else ""
    bm, rm = _business_revenue_models(about)

    cxo_block = (
        f"Primary outreach contact (recipient): {recipient_li or '—'} | "
        f"Suggested research: CEO / COO / CDO / CRO on {site or 'company site + LinkedIn'} — verify via leadership page."
    )
    cxo_li = " | ".join([x for x in [str(recipient_li or "").strip(), str(company_li or "").strip()] if x and x != "nan"])

    strategic: Dict[str, str] = {
        "connection_type": "",
        "business_model": "",
        "revenue_model": "",
        "strategic_site": site,
        "what_building": "",
        "conversation_topic": "",
        "humanizing": "",
        "emotional_framework": "",
    }

    if priority >= 80:
        strategic["connection_type"] = (
            "Outbound — LinkedIn-led; use recipient URL as thread anchor; parallel path to CXO via warm intro if available."
        )
        strategic["business_model"] = bm
        strategic["revenue_model"] = rm
        strategic["what_building"] = (about[:280] + "…") if len(about) > 280 else (about or f"{company} — FS proposition refinement from public signals.")
        strategic["conversation_topic"] = (
            f"How {company} is industrializing trustworthy AI and evidence for regulators/clients without slowing shipping — "
            f"starting from {segment.lower()} realities."
        )
        strategic["humanizing"] = (
            "Acknowledge execution pressure: teams are asked to prove outcomes, not just ship features. Offer a concrete 30-day path: "
            "data contract + one workflow + one governed agent pilot."
        )
        strategic["emotional_framework"] = (
            "Logical channel: ROI via fewer manual controls, faster reporting cycles, defensible AI. "
            "Emotional channel: credibility with the board/regulators, reduced fear of 'AI incidents', pride in a modern platform story."
        )

    return {
        "segmentation": segment,
        "segment_label": segment,
        "bis": bis,
        "lqs": lqs,
        "priority_score": priority,
        "high_propensity": high,
        "pain_hook": pain,
        "offerings": offerings,
        "cxo_contacts": cxo_block,
        "cxo_linkedin": cxo_li,
        "cxo_emails": "",
        **strategic,
    }


def audit_existing_columns(df: pd.DataFrame) -> Dict[str, Any]:
    """Summarize which output-like columns exist and fill rates."""
    report: Dict[str, Any] = {"columns_detected": [], "fill_rates": {}}
    for col in df.columns:
        ck = _canonical_output_key_for_column(str(col))
        if ck:
            report["columns_detected"].append({"file_column": col, "maps_to": ck})
            series = df[col]
            nonblank = sum(1 for v in series if not _blank(v))
            report["fill_rates"][str(col)] = {
                "nonblank": int(nonblank),
                "total": int(len(series)),
            }
    return report


def process_dataframe(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    colmap = {
        "name": _find_column(df, NAME_ALIASES),
        "company_li": _find_column(df, COMPANY_LI_ALIASES),
        "website": _find_column(df, WEBSITE_ALIASES),
        "revenue": _find_column(df, REV_ALIASES),
        "employees": _find_column(df, EMP_ALIASES),
        "about": _find_column(df, ABOUT_ALIASES),
        "recipient_li": _find_column(df, RECIPIENT_LI_ALIASES),
    }

    # Map existing columns to canonical output keys (first wins) for skip logic
    existing_canonical: Dict[str, str] = {}
    for c in df.columns:
        ck = _canonical_output_key_for_column(str(c))
        if ck and ck not in existing_canonical:
            existing_canonical[ck] = c

    audit = audit_existing_columns(df)
    audit["input_mapping"] = {k: v for k, v in colmap.items() if v}

    out = df.copy()
    display_by_key = dict(OUTPUT_SPECS)

    for idx in out.index:
        computed = enrich_row(out.loc[idx], {k: v for k, v in colmap.items() if v})
        for key, display in OUTPUT_SPECS:
            if key in existing_canonical:
                col_name = existing_canonical[key]
                if not _blank(out.at[idx, col_name]):
                    continue
                out.at[idx, col_name] = computed[key]
            else:
                if display not in out.columns:
                    out[display] = ""
                if _blank(out.at[idx, display]):
                    out.at[idx, display] = computed[key]

    return out, audit


def read_table(path: Path, sheet: Optional[Any]) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf in {".xlsx", ".xlsm"}:
        return pd.read_excel(path, sheet_name=sheet if sheet is not None else 0)
    if suf in {".csv"}:
        return pd.read_csv(path)
    raise ValueError(f"Unsupported input type: {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Kreatorverse FS prospect enrichment")
    ap.add_argument("--input", "-i", required=True, help="Input .csv or .xlsx")
    ap.add_argument("--output", "-o", help="Output .csv path (default: alongside input)")
    ap.add_argument("--sheet", default=None, help="Excel sheet name or index (default 0)")
    args = ap.parse_args()

    in_path = Path(args.input).expanduser().resolve()
    if not in_path.is_file():
        raise SystemExit(f"Input not found: {in_path}")

    sheet: Any = 0
    if args.sheet is not None:
        try:
            sheet = int(args.sheet)
        except ValueError:
            sheet = args.sheet

    df = read_table(in_path, sheet)
    enriched, audit = process_dataframe(df)

    out_path = Path(args.output).expanduser().resolve() if args.output else in_path.with_suffix(".enriched.csv")
    enriched.to_csv(out_path, index=False, encoding="utf-8-sig")

    print("=== Enrichment complete ===")
    print(f"Rows: {len(enriched)}")
    print(f"Output: {out_path}")
    print("\n=== Existing output-like columns in input (not overwritten when filled) ===")
    if audit["columns_detected"]:
        for item in audit["columns_detected"]:
            fr = audit["fill_rates"].get(item["file_column"], {})
            print(f"  - {item['file_column']} -> {item['maps_to']} | filled {fr.get('nonblank')}/{fr.get('total')}")
    else:
        print("  (none detected — all generated columns are new)")
    print("\n=== Input field mapping used ===")
    for k, v in audit["input_mapping"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
