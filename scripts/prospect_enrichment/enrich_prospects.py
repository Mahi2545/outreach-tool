"""
Bulk prospect enrichment for outreach spreadsheets.

Design goals:
- Preserve any existing populated values (fill only blanks).
- Work on both .xlsx (first sheet by default) and .csv inputs.
- Produce a clean CSV output for upload into outreach tools.
- Optional best-effort web research for missing CXO contacts and pain points.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from urllib.parse import quote_plus, urlparse
from urllib.parse import parse_qs
from urllib.request import Request, urlopen


def _norm_col(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    # Covers float NaN, pandas.NA, NaT, etc.
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def _get_col(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    cols = {_norm_col(c): c for c in df.columns}
    for cand in candidates:
        key = _norm_col(cand)
        if key in cols:
            return cols[key]
    return None


def _ensure_col(df: pd.DataFrame, name: str) -> str:
    if name not in df.columns:
        df[name] = pd.NA
    return name


def _clip_score(x: Any) -> Optional[float]:
    try:
        if pd.isna(x):
            return None
        v = float(x)
        return max(0.0, min(100.0, v))
    except Exception:
        return None


@dataclass(frozen=True)
class EnrichmentConfig:
    high_priority_threshold: float = 80.0
    use_web: bool = False
    max_rows: Optional[int] = None
    sleep_seconds: float = 1.2
    timeout_seconds: float = 12.0
    cache_path: Optional[Path] = None


SEGMENT_TO_BUSINESS_MODEL = {
    "AI-Native FinTechs": "B2C or B2B2C fintech product, AI-first workflows",
    "Lending & RegTech": "Regulated financial services + compliance-heavy ops",
    "Platform & Payments": "Payments orchestration / platform infrastructure",
    "Investment Mgmt & Wealth Tech": "Wealth/investment platform with reporting obligations",
}

SEGMENT_TO_REVENUE_MODEL = {
    "AI-Native FinTechs": "Subscription + interchange/partner revenue (varies by product)",
    "Lending & RegTech": "SaaS (RegTech) or interest + fees (lenders), plus platform fees",
    "Platform & Payments": "Per-transaction / take-rate + platform fees",
    "Investment Mgmt & Wealth Tech": "AUM-based fees + subscription/platform fees",
}


def _shorten(text: Any, max_len: int = 180) -> str:
    t = str(text or "").strip()
    t = re.sub(r"\s+", " ", t)
    # Normalize common “smart quote” characters for CSV safety.
    t = (
        t.replace("“", "\"")
        .replace("”", "\"")
        .replace("’", "'")
        .replace("–", "-")
        .replace("—", "-")
        .replace("�", "-")
    )
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _derive_connection_type(row: pd.Series) -> str:
    v = row.get("Linkedin Connection", pd.NA)
    if isinstance(v, str) and v.strip():
        return v.strip()
    return "Not connected (cold)"


def _derive_business_model(segment_label: str) -> str:
    return SEGMENT_TO_BUSINESS_MODEL.get(segment_label, "B2B (likely), regulated/infra-adjacent")


def _derive_revenue_model(segment_label: str) -> str:
    return SEGMENT_TO_REVENUE_MODEL.get(segment_label, "Subscription and/or usage-based (likely)")


def _derive_strategic_site(row: pd.Series) -> Any:
    # Prefer explicit website if present; otherwise fall back to company LinkedIn.
    v = row.get("Company Website", pd.NA)
    if isinstance(v, str) and v.strip():
        return v.strip()
    return row.get("Company LinkedIn URL", pd.NA)


def _derive_what_building(row: pd.Series) -> str:
    about = row.get("About Company", "")
    company = row.get("Company Name", "")
    if _is_blank(about):
        return f"Core product/operations modernization at {company}".strip()
    return _shorten(about, 200)


def _derive_conversation_topic(row: pd.Series) -> str:
    pain = row.get("Pain Point ( Hook)", "")
    seg = row.get("Segment Label", "")
    if isinstance(pain, str) and pain.strip():
        return _shorten(pain, 160)
    if isinstance(seg, str) and seg.strip():
        return f"Operational + compliance acceleration for {seg}"
    return "Data/process modernization with measurable time-to-audit and time-to-decision gains"


def _derive_humanizing(row: pd.Series) -> str:
    company = row.get("Company Name", "your team")
    about = str(row.get("About Company", "") or "")
    # Light-touch, non-hallucinatory: only uses supplied text.
    if about.strip():
        return f'Noticed your positioning: "{_shorten(about, 120)}" - curious what internal workflow is currently the biggest drag on shipping.'
    return f"Curious what the #1 bottleneck is right now at {company} between data, process, and execution."


def _derive_emotional_framework(row: pd.Series) -> str:
    # Dual-channel: rational + emotional payoff.
    pain = str(row.get("Pain Point ( Hook)", "") or "").strip().lower()
    if "audit" in pain or "fca" in pain or "basel" in pain or "mifid" in pain:
        rational = "Reduce compliance cost, improve auditability, shorten time-to-report"
        emotional = "Confidence going into audits; fewer fire-drills and escalations"
    elif "reconciliation" in pain or "fragment" in pain or "schema" in pain:
        rational = "Single source of truth, fewer breaks, faster decisions"
        emotional = "Relief from constant exceptions; trust in numbers"
    else:
        rational = "Higher throughput, fewer handoffs, measurable cycle-time reduction"
        emotional = "Less operational anxiety; teams feel in control"
    return f"Rational: {rational}. Emotional: {emotional}."


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        if data and data.strip():
            self._chunks.append(data.strip())

    def text(self) -> str:
        return " ".join(self._chunks)


def _http_get(url: str, timeout_seconds: float) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ProspectEnrichment/1.0; +https://kreatorverse.example)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    with urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read()
        # Best-effort decode; many sites are utf-8.
        try:
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            return raw.decode(errors="ignore")


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    t = parser.text()
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _domain_from_url(url: str) -> Optional[str]:
    try:
        u = urlparse(url)
        if not u.netloc:
            return None
        return u.netloc.lower().lstrip("www.")
    except Exception:
        return None


def _safe_url_join(base: str, path: str) -> str:
    b = base.rstrip("/")
    p = path if path.startswith("/") else "/" + path
    return b + p


def _find_emails(text: str) -> list[str]:
    # Conservative: only explicit emails.
    emails = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.I)
    out: list[str] = []
    seen = set()
    for e in emails:
        e = e.strip().lower()
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def _extract_linkedin_people_links(html: str) -> list[str]:
    # Find linkedin.com/in/... links.
    links = re.findall(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[^\s\"'<>?#]+", html, flags=re.I)
    out: list[str] = []
    seen = set()
    for l in links:
        # Strip common trailing punctuation
        l = l.rstrip(").,;\"'")
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out[:10]


def _duckduckgo_search(query: str, timeout_seconds: float) -> str:
    # DuckDuckGo HTML endpoint (best-effort; may rate limit).
    url = "https://duckduckgo.com/html/?q=" + quote_plus(query)
    return _http_get(url, timeout_seconds)


def _serper_search(query: str, timeout_seconds: float) -> list[str]:
    """
    Optional: use Serper (Google Search API) when SERPER_API_KEY is set.
    Returns a list of organic result links.
    """
    key = os.getenv("SERPER_API_KEY", "").strip()
    if not key:
        return []
    payload = json.dumps({"q": query, "num": 5}).encode("utf-8")
    req = Request(
        "https://google.serper.dev/search",
        data=payload,
        headers={
            "X-API-KEY": key,
            "Content-Type": "application/json",
            "User-Agent": "ProspectEnrichment/1.0",
        },
        method="POST",
    )
    with urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    try:
        data = json.loads(raw)
    except Exception:
        return []
    links: list[str] = []
    for item in (data.get("organic") or [])[:5]:
        link = item.get("link")
        if isinstance(link, str) and link.startswith("http"):
            links.append(link)
    return links


def _extract_search_results(html: str) -> list[tuple[str, str]]:
    # Very lightweight parsing: capture result title and URL.
    # DuckDuckGo uses <a class="result__a" href="...">Title</a>
    results = re.findall(r'class="result__a"\s+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.I)
    cleaned: list[tuple[str, str]] = []
    for href, title in results[:10]:
        # DuckDuckGo often wraps outbound links as /l/?uddg=<encoded>.
        try:
            u = urlparse(href)
            if u.netloc.endswith("duckduckgo.com") and u.path.startswith("/l/"):
                qs = parse_qs(u.query or "")
                if "uddg" in qs and qs["uddg"]:
                    href = qs["uddg"][0]
        except Exception:
            pass
        title_txt = re.sub(r"<.*?>", "", title)
        title_txt = _shorten(title_txt, 120)
        cleaned.append((href, title_txt))
    return cleaned


def _guess_relevant_pages(base_site: str) -> list[str]:
    return [
        base_site,
        _safe_url_join(base_site, "/about"),
        _safe_url_join(base_site, "/company"),
        _safe_url_join(base_site, "/team"),
        _safe_url_join(base_site, "/leadership"),
        _safe_url_join(base_site, "/careers"),
        _safe_url_join(base_site, "/security"),
        _safe_url_join(base_site, "/compliance"),
    ]


def _infer_pain_point(segment_label: str, about: str, site_text: str) -> str:
    blob = " ".join([segment_label or "", about or "", site_text or ""]).lower()
    has = lambda *terms: any(t.lower() in blob for t in terms)

    # Compliance/reg keywords (UK/EU finance oriented).
    fca = has("fca", "consumer duty")
    aml = has("aml", "anti-money", "money laundering", "kyc", "sanctions")
    psd2 = has("psd2", "open banking", "ais", "pis")
    mifid = has("mifid", "priips", "ucits", "aum")
    basel = has("basel", "basel iv", "capital requirements")
    reconciliation = has("reconciliation", "settlement", "chargeback", "disputes", "breaks")
    audit = has("audit", "audit trail", "governance", "model risk", "validation")
    workflow = has("workflow", "manual", "spreadsheet", "handoff", "exceptions", "back office")
    realtime = has("real-time", "real time", "instant", "faster")

    if segment_label == "Platform & Payments":
        return (
            "Payment ops data is fragmented across rails, PSPs, fraud tools, and chargeback systems — reconciliation breaks and exception queues "
            "create blind spots in real-time risk, settlement, and dispute handling; scaling cross-rail reporting and controls becomes a constant fire-drill."
        )
    if segment_label == "Investment Mgmt & Wealth Tech":
        if mifid or audit:
            return (
                "Portfolio + client data is split across custody, OMS/PMS, and reporting tools — producing consistent MiFID II/PRIIPs reporting and governance "
                "requires manual reconciliation, leaving audit trails brittle and slowing product iteration."
            )
        return (
            "Portfolio, client, and reporting data is scattered across vendors and internal systems — creating reconciliation breaks, slow reporting cycles, "
            "and brittle auditability as the platform scales."
        )
    if segment_label == "Lending & RegTech":
        if fca or basel or aml:
            return (
                "Loan book, KYC/AML, and regulatory data sits across origination, servicing, and reporting systems with no unified schema — closing FCA/Basel "
                "compliance gaps can't be sustained with manual reconciliation; decision latency and fragmented audit trails compound regulatory risk."
            )
        return (
            "Credit + compliance data is spread across origination, servicing, and third-party checks — manual exceptions pile up, slowing decisions and creating "
            "audit trail gaps as volumes grow."
        )
    if segment_label == "AI-Native FinTechs":
        if audit or workflow:
            return (
                "Process entropy sits between AI decisions and operational execution — exceptions, vendor dependencies, and non-standard review workflows reintroduce "
                "manual delay; model decision audit trails are fragmented, increasing governance exposure as you scale."
            )
        return (
            "AI-driven decisions don't consistently translate into executed outcomes — exception handling, vendor APIs, and inconsistent workflows create throughput drag "
            "and operational risk."
        )

    # Fallback, using detected signals.
    parts = []
    if fca:
        parts.append("FCA Consumer Duty readiness")
    if aml:
        parts.append("KYC/AML + sanctions controls")
    if psd2:
        parts.append("Open Banking / PSD2 operational controls")
    if basel:
        parts.append("Basel-aligned reporting + auditability")
    if mifid:
        parts.append("MiFID/PRIIPs reporting")
    if reconciliation:
        parts.append("cross-system reconciliation breaks")
    if audit:
        parts.append("audit trail + governance gaps")
    if workflow or realtime:
        parts.append("manual exception queues slowing decisions")
    joined = ", ".join(parts[:4]) if parts else "data + process fragmentation"
    return (
        f"Key operating data is fragmented across systems, creating {joined} — manual reconciliations and exception handling slow execution and make controls harder to prove at scale."
    )


def _web_research(company_name: str, company_site: Optional[str], segment_label: str, timeout_seconds: float) -> dict[str, Any]:
    """
    Best-effort research to discover:
    - leadership/CXO names + linkedin URLs (if present on site or in search results)
    - explicit emails found on site (no guessing)
    - site text signals to improve pain point
    """
    out: dict[str, Any] = {
        "evidence": [],
        "linkedin_people": [],
        "emails": [],
        "site_text": "",
        "cxo_names": [],
        "official_site": "",
    }

    site = None
    if company_site and isinstance(company_site, str) and company_site.strip():
        site = company_site.strip()
        if not re.match(r"^https?://", site, flags=re.I):
            site = "https://" + site

    # If website not provided, try to discover official site via search.
    if not site:
        try:
            q_site = f"{company_name} official website"
            serper_links = _serper_search(q_site, timeout_seconds)
            if serper_links:
                out["evidence"].append("serper:" + q_site)
                candidates = serper_links
            else:
                q_site = f"{company_name} official website -site:duckduckgo.com"
                sr_html = _duckduckgo_search(q_site, timeout_seconds)
                out["evidence"].append("duckduckgo:" + q_site)
                candidates = [href for href, _t in _extract_search_results(sr_html)]

            for href in candidates:
                h = href.lower()
                if any(
                    bad in h
                    for bad in [
                        "duckduckgo.com",
                        "linkedin.com",
                        "wikipedia.org",
                        "crunchbase.com",
                        "facebook.com",
                        "twitter.com",
                        "x.com",
                    ]
                ):
                    continue
                dom = _domain_from_url(href)
                if dom:
                    site = "https://" + dom
                    break
        except Exception:
            pass
    if site:
        out["official_site"] = site

    # 1) Fetch a few likely pages from website (if provided).
    if site:
        texts: list[str] = []
        for url in _guess_relevant_pages(site):
            try:
                html = _http_get(url, timeout_seconds)
                out["evidence"].append(url)
                out["linkedin_people"].extend(_extract_linkedin_people_links(html))
                txt = _html_to_text(html)
                texts.append(txt)
                out["emails"].extend(_find_emails(html))
                # Throttle between pages; callers throttle between rows too.
                time.sleep(0.2)
            except Exception:
                continue
        out["site_text"] = _shorten(" ".join(texts), 4000)

    # 2) Search for CEO/CXO LinkedIn profile (best-effort).
    try:
        q = f"{company_name} CEO site:linkedin.com/in"
        if segment_label:
            q = f"{company_name} CEO {segment_label} site:linkedin.com/in"
        serper_links = _serper_search(q, timeout_seconds)
        if serper_links:
            out["evidence"].append("serper:" + q)
            candidates = serper_links
        else:
            sr_html = _duckduckgo_search(q, timeout_seconds)
            out["evidence"].append("duckduckgo:" + q)
            candidates = [href for href, _t in _extract_search_results(sr_html)]

        for href in candidates:
            if "linkedin.com/in/" in href:
                out["linkedin_people"].append(href)
    except Exception:
        pass

    # Deduplicate and trim.
    seen = set()
    people = []
    for l in out["linkedin_people"]:
        l = l.strip()
        if not l:
            continue
        if l not in seen:
            seen.add(l)
            people.append(l)
    out["linkedin_people"] = people[:6]
    out["emails"] = list(dict.fromkeys([e.lower() for e in out["emails"]]))[:5]

    return out


def enrich_df(df: pd.DataFrame, cfg: EnrichmentConfig) -> pd.DataFrame:
    # Normalize a few expected columns if they are missing; never drop originals.
    # Add required-but-missing input columns as blanks (so downstream systems have schema).
    _ensure_col(df, "Company Website")
    _ensure_col(df, "Recipient LinkedIn URL")

    # Add required strategic/outreach columns.
    for col in [
        "Connection Type",
        "Business Model",
        "Revenue Model",
        "Strategic Site",
        "What they are building",
        "Conversation Topic",
        "Humanizing the conversation",
        "Emotional Dual Channel Emotional Framework",
        "Research Evidence",
    ]:
        _ensure_col(df, col)

    # Prefer existing priority; else compute from BIS/LQS if present.
    pr_col = _get_col(df, "Priority", "Priority Score (0-100)", "Priority Score")
    bis_col = _get_col(df, "BUYING INTENT SCORE", "Buying Intent Score (BIS)", "Buying Intent Score")
    lqs_col = _get_col(df, "Lead Quality Score", "LQS", "Lead Quality Score (LQS)")

    if pr_col is None:
        pr_col = _ensure_col(df, "Priority")

    def compute_priority(row: pd.Series) -> Optional[float]:
        existing = _clip_score(row.get(pr_col))
        if existing is not None:
            return existing
        bis = _clip_score(row.get(bis_col)) if bis_col else None
        lqs = _clip_score(row.get(lqs_col)) if lqs_col else None
        if bis is None and lqs is None:
            return None
        if bis is None:
            return lqs
        if lqs is None:
            return bis
        # Weighted towards buying intent.
        return round(0.55 * bis + 0.45 * lqs, 1)

    df[pr_col] = df.apply(compute_priority, axis=1)

    # Fill strategic columns only if blank.
    cache: dict[str, Any] = {}
    if cfg.cache_path:
        try:
            if cfg.cache_path.exists():
                cache = json.loads(cfg.cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    def fill_row(row: pd.Series) -> pd.Series:
        priority = _clip_score(row.get(pr_col)) or 0.0
        seg_label = str(row.get("Segment Label", "") or "").strip()

        if _is_blank(row.get("Connection Type")):
            row["Connection Type"] = _derive_connection_type(row)

        if _is_blank(row.get("Business Model")):
            row["Business Model"] = _derive_business_model(seg_label)

        if _is_blank(row.get("Revenue Model")):
            row["Revenue Model"] = _derive_revenue_model(seg_label)

        if _is_blank(row.get("Strategic Site")):
            row["Strategic Site"] = _derive_strategic_site(row)

        if _is_blank(row.get("What they are building")):
            row["What they are building"] = _derive_what_building(row)

        if _is_blank(row.get("Conversation Topic")):
            row["Conversation Topic"] = _derive_conversation_topic(row)

        # Optional web research: run for high-priority leads when key fields are missing.
        if cfg.use_web and priority >= cfg.high_priority_threshold:
            needs_research = any(
                _is_blank(row.get(c))
                for c in [
                    "Company Website",
                    "Key CxO Contacts",
                    "Linkedin URLs",
                    "Email ID",
                    "Research Evidence",
                ]
            )
            if needs_research:
                company = str(row.get("Company Name", "") or "").strip()
                if company:
                    site = row.get("Company Website", pd.NA)
                    cache_key = (company.lower() + "|" + ("" if _is_blank(site) else str(site))).strip()
                    research = cache.get(cache_key)
                    if not isinstance(research, dict):
                        research = _web_research(company, None if _is_blank(site) else str(site), seg_label, cfg.timeout_seconds)
                        cache[cache_key] = research
                        time.sleep(cfg.sleep_seconds)

                    discovered_site = str(research.get("official_site") or "").strip()
                    if _is_blank(row.get("Company Website")) and discovered_site:
                        row["Company Website"] = discovered_site

                    if _is_blank(row.get("Linkedin URLs")) and research.get("linkedin_people"):
                        row["Linkedin URLs"] = "; ".join(research["linkedin_people"])
                    if _is_blank(row.get("Email ID")) and research.get("emails"):
                        row["Email ID"] = research["emails"][0]
                    if _is_blank(row.get("Email IDs")) and research.get("emails"):
                        row["Email IDs"] = "; ".join(research["emails"])
                    if _is_blank(row.get("Key CxO Contacts")) and research.get("linkedin_people"):
                        row["Key CxO Contacts"] = "CXO LinkedIn profiles discovered (name lookup needed)"

                    evs = research.get("evidence") or []
                    if evs and _is_blank(row.get("Research Evidence")):
                        row["Research Evidence"] = "; ".join([_shorten(e, 140) for e in evs[:6]])

        # Pain point is a primary output for high-priority prospects.
        if priority >= cfg.high_priority_threshold:
            if _is_blank(row.get("Pain Point ( Hook)")) or (isinstance(row.get("Pain Point ( Hook)"), str) and len(str(row.get("Pain Point ( Hook)")).strip()) < 80):
                about = str(row.get("About Company", "") or "")
                site_text = ""
                evidence = []

                # Optional web research to strengthen pain point and discover contacts.
                if cfg.use_web:
                    company = str(row.get("Company Name", "") or "").strip()
                    if company:
                        site = row.get("Company Website", pd.NA)
                        cache_key = (str(company).lower() + "|" + ("" if _is_blank(site) else str(site))).strip()
                        research = cache.get(cache_key)
                        if not isinstance(research, dict):
                            research = _web_research(company, None if _is_blank(site) else str(site), seg_label, cfg.timeout_seconds)
                            cache[cache_key] = research
                            time.sleep(cfg.sleep_seconds)

                        site_text = str(research.get("site_text") or "")
                        evidence = list(research.get("evidence") or [])

                        # Fill contacts only if missing (no guessing).
                        if _is_blank(row.get("Linkedin URLs")) and research.get("linkedin_people"):
                            row["Linkedin URLs"] = "; ".join(research["linkedin_people"])
                        if _is_blank(row.get("Email ID")) and research.get("emails"):
                            row["Email ID"] = research["emails"][0]
                        if _is_blank(row.get("Email IDs")) and research.get("emails"):
                            row["Email IDs"] = "; ".join(research["emails"])
                        if _is_blank(row.get("Key CxO Contacts")) and research.get("linkedin_people"):
                            # We don't infer names reliably without profile parsing; store as "CXO LinkedIn(s)".
                            row["Key CxO Contacts"] = "CXO LinkedIn profiles discovered (name lookup needed)"

                if _is_blank(row.get("Pain Point ( Hook)")):
                    row["Pain Point ( Hook)"] = _infer_pain_point(seg_label, about, site_text)
                else:
                    # If short/weak, overwrite only for high priority.
                    row["Pain Point ( Hook)"] = _infer_pain_point(seg_label, about, site_text)

                if evidence and _is_blank(row.get("Research Evidence")):
                    row["Research Evidence"] = "; ".join([_shorten(e, 140) for e in evidence[:6]])

        if _is_blank(row.get("Humanizing the conversation")):
            # Only populate for high priority (per prompt).
            if priority >= cfg.high_priority_threshold:
                row["Humanizing the conversation"] = _derive_humanizing(row)

        if _is_blank(row.get("Emotional Dual Channel Emotional Framework")):
            # Only populate for high priority (per prompt).
            if priority >= cfg.high_priority_threshold:
                row["Emotional Dual Channel Emotional Framework"] = _derive_emotional_framework(row)

        return row

    if cfg.max_rows is not None:
        # Enrich first N rows; keep rest unchanged.
        head = df.head(cfg.max_rows).apply(fill_row, axis=1)
        tail = df.iloc[cfg.max_rows:].copy()
        df = pd.concat([head, tail], axis=0)
    else:
        df = df.apply(fill_row, axis=1)

    if cfg.cache_path:
        try:
            cfg.cache_path.parent.mkdir(parents=True, exist_ok=True)
            cfg.cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # Add a clear flag for high-propensity buyers (doesn't overwrite anything).
    if "High Propensity Buyer" not in df.columns:
        df["High Propensity Buyer"] = df[pr_col].apply(lambda x: bool((_clip_score(x) or 0.0) >= cfg.high_priority_threshold))

    # Provide a standardized "Priority Score (0-100)" column without breaking existing sheets.
    if "Priority Score (0-100)" not in df.columns:
        df["Priority Score (0-100)"] = df[pr_col]

    return df


def load_input(path: Path, sheet: Optional[str]) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        xl = pd.ExcelFile(path)
        chosen = sheet or xl.sheet_names[0]
        return xl.parse(chosen)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Enrich prospect file for outreach (preserve existing values).")
    ap.add_argument("--input", required=True, help="Path to input .xlsx or .csv")
    ap.add_argument("--output", required=True, help="Path to output .csv")
    ap.add_argument("--sheet", default=None, help="Excel sheet name (defaults to first sheet)")
    ap.add_argument("--high-priority-threshold", type=float, default=80.0)
    ap.add_argument("--use-web", action="store_true", help="Best-effort web research to fill missing contacts and strengthen pain points (slower).")
    ap.add_argument("--max-rows", type=int, default=None, help="Only enrich first N rows (useful for testing web mode).")
    ap.add_argument("--sleep-seconds", type=float, default=1.2, help="Delay between row web lookups.")
    ap.add_argument("--timeout-seconds", type=float, default=12.0, help="HTTP timeout for web fetch/search.")
    ap.add_argument("--cache", default=None, help="Path to JSON cache file (recommended for --use-web).")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    df = load_input(in_path, args.sheet)

    cache_path = Path(args.cache) if args.cache else (out_path.parent / ".prospect_enrichment_cache.json" if args.use_web else None)
    cfg = EnrichmentConfig(
        high_priority_threshold=args.high_priority_threshold,
        use_web=bool(args.use_web),
        max_rows=args.max_rows,
        sleep_seconds=float(args.sleep_seconds),
        timeout_seconds=float(args.timeout_seconds),
        cache_path=cache_path,
    )
    enriched = enrich_df(df, cfg)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(out_path, index=False)
    print(f"Wrote {len(enriched)} rows to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

