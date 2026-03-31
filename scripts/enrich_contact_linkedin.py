import argparse
import json
import random
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
import requests
from rapidfuzz import fuzz


NAME_CANDIDATE_COLUMNS = [
    "Full Name",
    "Name",
    "Contact Name",
    "Firstname Lastname",
    "Associated Contact",
    "Contact with Primary Company",
]

FIRST_NAME_CANDIDATE_COLUMNS = ["First Name", "Firstname", "Contact First Name"]
LAST_NAME_CANDIDATE_COLUMNS = ["Last Name", "Lastname", "Contact Last Name"]
COMPANY_CANDIDATE_COLUMNS = ["Company Name", "Company", "Associated Company"]


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def slug_tokens_from_text(text: str) -> List[str]:
    cleaned = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return [t for t in cleaned.split() if t]


def normalize_linkedin_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = "https"
    netloc = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.rstrip("/")
    return f"{scheme}://{netloc}{path}"


def is_personal_linkedin_url(url: str) -> bool:
    lowered = url.lower()
    return "linkedin.com/in/" in lowered and "linkedin.com/company/" not in lowered


def pick_column(columns: List[str], candidates: List[str]) -> Optional[str]:
    mapping = {c.lower().strip(): c for c in columns}
    for candidate in candidates:
        if candidate.lower() in mapping:
            return mapping[candidate.lower()]
    return None


def infer_columns(df: pd.DataFrame) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    columns = [str(c) for c in df.columns.tolist()]
    full_name_col = pick_column(columns, NAME_CANDIDATE_COLUMNS)
    first_name_col = pick_column(columns, FIRST_NAME_CANDIDATE_COLUMNS)
    last_name_col = pick_column(columns, LAST_NAME_CANDIDATE_COLUMNS)
    company_col = pick_column(columns, COMPANY_CANDIDATE_COLUMNS)
    return full_name_col, first_name_col, last_name_col, company_col


def build_full_name(row: pd.Series, full_name_col: Optional[str], first_name_col: Optional[str], last_name_col: Optional[str]) -> str:
    if full_name_col and pd.notna(row.get(full_name_col)):
        return normalize_spaces(str(row.get(full_name_col)))

    first_name = str(row.get(first_name_col, "")).strip() if first_name_col else ""
    last_name = str(row.get(last_name_col, "")).strip() if last_name_col else ""
    return normalize_spaces(f"{first_name} {last_name}")


def extract_contact_names(raw_value: str) -> List[str]:
    if not raw_value:
        return []

    names: List[str] = []
    parts = [p.strip() for p in str(raw_value).split(";") if p.strip()]
    for part in parts:
        # Pattern examples:
        # "Lakshmi Mokkarala (lakshmimokkarala@bbh.com)"
        # "John Smith"
        name_only = re.sub(r"\s*\([^)]*\)\s*$", "", part).strip()
        if name_only and "@" not in name_only:
            names.append(name_only)
    return names


def extract_slug_tokens(url: str) -> List[str]:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if "/in/" not in path:
        return []
    slug = path.split("/in/", 1)[1].strip("/")
    slug = re.sub(r"[-_./]+", " ", slug)
    return slug_tokens_from_text(slug)


def score_candidate(full_name: str, company_name: str, url: str, title: str, snippet: str) -> float:
    score = 0.0
    slug_tokens = extract_slug_tokens(url)
    name_tokens = slug_tokens_from_text(full_name)
    company_tokens = slug_tokens_from_text(company_name)
    blob = f"{title} {snippet}".lower()

    if slug_tokens and name_tokens:
        overlap = len(set(slug_tokens) & set(name_tokens))
        score += overlap * 15
        score += fuzz.token_set_ratio(" ".join(slug_tokens), " ".join(name_tokens)) * 0.35

    if company_tokens:
        company_hits = sum(1 for token in company_tokens if token in blob)
        score += min(company_hits, 3) * 12

    if "linkedin" in blob:
        score += 5

    # Small preference for cleaner profile URLs
    if "detail/recent-activity" not in url and "overlay/contact-info" not in url:
        score += 4

    return round(score, 2)


def confidence_band(score: float) -> str:
    if score >= 72:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def run_search(query: str, max_results: int = 6, retries: int = 1, timeout_seconds: float = 6.0) -> List[Dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    for attempt in range(retries):
        try:
            response = requests.get(
                "https://duckduckgo.com/html/",
                params={"q": query},
                headers=headers,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            html = response.text

            # Parse result blocks from DDG HTML endpoint.
            matches = re.findall(
                r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                html,
                flags=re.IGNORECASE | re.DOTALL,
            )

            items: List[Dict] = []
            for href, title_html in matches[: max_results * 2]:
                href = href.strip()
                title = re.sub(r"<[^>]+>", "", title_html).strip()
                body = ""

                # DDG frequently wraps external links as /l/?uddg=<urlencoded>.
                if href.startswith("/l/?"):
                    parsed = urlparse(href)
                    qs = parse_qs(parsed.query)
                    raw_target = qs.get("uddg", [""])[0]
                    href = unquote(raw_target) if raw_target else href

                items.append({"href": href, "title": title, "body": body})
                if len(items) >= max_results:
                    break

            return items
        except Exception:
            wait = min(12, 2 ** attempt + random.uniform(0.2, 1.2))
            print(f"[search retry] attempt={attempt + 1}/{retries}, waiting={wait:.1f}s", flush=True)
            time.sleep(wait)
    return []


def write_checkpoint(checkpoint_path: Path, current_index: int) -> None:
    checkpoint_path.write_text(json.dumps({"last_processed_index": current_index}), encoding="utf-8")


def read_checkpoint(checkpoint_path: Path) -> int:
    if not checkpoint_path.exists():
        return -1
    try:
        data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        return int(data.get("last_processed_index", -1))
    except Exception:
        return -1


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich contacts with personal LinkedIn URLs.")
    parser.add_argument("--input", required=True, help="Input XLSX path")
    parser.add_argument("--output", default="", help="Output XLSX path (optional)")
    parser.add_argument("--checkpoint-every", type=int, default=50, help="Save checkpoint every N rows")
    parser.add_argument("--sleep-min", type=float, default=0.7, help="Minimum sleep between requests")
    parser.add_argument("--sleep-max", type=float, default=1.8, help="Maximum sleep between requests")
    parser.add_argument("--start-index", type=int, default=0, help="Start row index")
    parser.add_argument("--limit", type=int, default=0, help="Process only first N rows from start-index")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint if present")
    parser.add_argument("--search-retries", type=int, default=1, help="Search retries per query")
    parser.add_argument("--search-timeout", type=float, default=6.0, help="HTTP timeout per search query in seconds")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = input_path.with_name(f"{input_path.stem}.enriched.xlsx")

    checkpoint_path = output_path.with_suffix(".checkpoint.json")

    df = pd.read_excel(input_path)
    full_name_col, first_name_col, last_name_col, company_col = infer_columns(df)

    if not full_name_col and not (first_name_col and last_name_col):
        raise ValueError("Could not infer contact name columns. Please add Full Name or First Name + Last Name.")
    if not company_col:
        company_col = ""

    if "Contact LinkedIn" not in df.columns:
        df["Contact LinkedIn"] = ""
    else:
        df["Contact LinkedIn"] = df["Contact LinkedIn"].astype(str)
    if "LinkedIn Confidence" not in df.columns:
        df["LinkedIn Confidence"] = ""
    else:
        df["LinkedIn Confidence"] = df["LinkedIn Confidence"].astype(str)
    if "LinkedIn Score" not in df.columns:
        df["LinkedIn Score"] = ""
    else:
        df["LinkedIn Score"] = df["LinkedIn Score"].astype(str)
    if "LinkedIn Query" not in df.columns:
        df["LinkedIn Query"] = ""
    else:
        df["LinkedIn Query"] = df["LinkedIn Query"].astype(str)

    start_index = args.start_index
    if args.resume:
        last_processed = read_checkpoint(checkpoint_path)
        if last_processed >= 0:
            start_index = max(start_index, last_processed + 1)

    end_index = len(df)
    if args.limit > 0:
        end_index = min(end_index, start_index + args.limit)

    print(f"Rows: {len(df)}")
    print(f"Name columns: full={full_name_col}, first={first_name_col}, last={last_name_col}")
    print(f"Company column: {company_col or '(none detected)'}")
    print(f"Processing index range: {start_index} to {end_index - 1}")
    print(f"Output: {output_path}")

    start_time = time.time()
    processed = 0
    for idx in range(start_index, end_index):
            row = df.iloc[idx]
            full_name = build_full_name(row, full_name_col, first_name_col, last_name_col)
            contact_names = extract_contact_names(full_name)
            if not contact_names and full_name:
                contact_names = [full_name]
            if not contact_names:
                continue
            if processed % 5 == 0:
                print(f"Working row {idx} ({processed} done so far)...", flush=True)

            company_name = ""
            if company_col and pd.notna(row.get(company_col)):
                company_name = normalize_spaces(str(row.get(company_col)))

            matched_urls: List[str] = []
            score_list: List[float] = []
            confidence_list: List[str] = []
            query_list: List[str] = []

            for contact_name in contact_names:
                query = f"\"{contact_name}\" \"{company_name}\" site:linkedin.com/in" if company_name else f"\"{contact_name}\" site:linkedin.com/in"
                results = run_search(
                    query=query,
                    max_results=8,
                    retries=max(1, args.search_retries),
                    timeout_seconds=max(1.0, args.search_timeout),
                )

                if company_name:
                    has_profile_result = any(is_personal_linkedin_url(str(item.get("href", ""))) for item in results)
                    if not has_profile_result:
                        fallback_query = f"\"{contact_name}\" site:linkedin.com/in"
                        fallback_results = run_search(
                            query=fallback_query,
                            max_results=8,
                            retries=max(1, args.search_retries),
                            timeout_seconds=max(1.0, args.search_timeout),
                        )
                        results.extend(fallback_results)
                        query = f"{query} || {fallback_query}"

                best_url = ""
                best_score = 0.0
                for item in results:
                    url = str(item.get("href", "")).strip()
                    title = str(item.get("title", "")).strip()
                    snippet = str(item.get("body", "")).strip()
                    if not url or not is_personal_linkedin_url(url):
                        continue

                    url = normalize_linkedin_url(url)
                    score = score_candidate(contact_name, company_name, url, title, snippet)
                    if score > best_score:
                        best_score = score
                        best_url = url

                matched_urls.append(best_url)
                score_list.append(best_score)
                confidence_list.append(confidence_band(best_score) if best_url else "low")
                query_list.append(query)

            df.at[idx, "Contact LinkedIn"] = ";".join(matched_urls)
            df.at[idx, "LinkedIn Score"] = ";".join(str(round(s, 2)) for s in score_list)
            df.at[idx, "LinkedIn Confidence"] = ";".join(confidence_list)
            df.at[idx, "LinkedIn Query"] = " || ".join(query_list)

            processed += 1
            if processed % 10 == 0:
                elapsed = time.time() - start_time
                print(f"Progress: processed={processed}, sheet_row_index={idx}, elapsed={elapsed:.1f}s", flush=True)
            if processed % args.checkpoint_every == 0:
                df.to_excel(output_path, index=False)
                write_checkpoint(checkpoint_path, idx)
                print(f"Checkpoint saved at row {idx}", flush=True)

            sleep_for = random.uniform(args.sleep_min, args.sleep_max)
            time.sleep(sleep_for)

    df.to_excel(output_path, index=False)
    write_checkpoint(checkpoint_path, end_index - 1 if end_index > 0 else -1)
    print("Finished.")
    print(f"Saved enriched file: {output_path}")
    print(f"Checkpoint file: {checkpoint_path}")


if __name__ == "__main__":
    main()
