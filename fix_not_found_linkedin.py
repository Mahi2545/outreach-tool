import asyncio
import pandas as pd
import sys
import os
import urllib.parse
from pathlib import Path
from typing import Optional

# Add the local linkedin_scraper to sys.path
SCRAPER_PATH = Path("scripts/linkedin_scraper/linkedin_scraper-3.1.1")
sys.path.append(str(SCRAPER_PATH.absolute()))

from linkedin_scraper import BrowserManager, PersonScraper

EXCEL_FILE = "Sample_linkedin_contacts_UPDATED.xlsx"
SESSION_FILE = "session.json"

async def search_for_profile(page, name, company):
    """Searches for a person on LinkedIn and returns the first profile URL found."""
    # Build search keywords
    keywords = f"{name}"
    if company and pd.notna(company):
        keywords += f" {company}"
    
    encoded_keywords = urllib.parse.quote(keywords)
    search_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_keywords}"
    
    try:
        print(f"Searching LinkedIn for: {keywords}")
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"   Navigation error: {e}")
        return None
        
    await page.wait_for_timeout(5000)
    
    # Extract links
    links = await page.locator("a").all()
    found_urls = []
    for link in links:
        href = await link.get_attribute("href")
        if href and "/in/" in href and not any(x in href for x in ["/in/ACoA", "linkedin.com/in/login"]):
            clean_url = href.split("?")[0]
            if clean_url.endswith("/"): clean_url = clean_url[:-1]
            if clean_url not in found_urls: found_urls.append(clean_url)
            
    if found_urls:
        return found_urls[0]
    
    # Fallback: Broad Search (Name only)
    if company:
        print(f"   No exact match found with company. Trying broader search for: {name}")
        search_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(name)}"
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(5000)
        except Exception as e:
            print(f"   Fallback navigation error: {e}")
            return None
        
        links = await page.locator("a").all()
        for link in links:
            href = await link.get_attribute("href")
            if href and "/in/" in href and not any(x in href for x in ["/in/ACoA", "linkedin.com/in/login"]):
                clean_url = href.split("?")[0]
                if clean_url.endswith("/"): clean_url = clean_url[:-1]
                return clean_url
                
    print("   No profile links found in search results.")
    return None

async def main():
    # Check if EXCEL_FILE exists
    if not os.path.exists(EXCEL_FILE):
        print(f"Error: {EXCEL_FILE} not found.")
        return

    # Load the Excel file
    df = pd.read_excel(EXCEL_FILE)
    
    # Identify rows without a valid LinkedIn URL (NOT_FOUND, SERP_ERROR, APOLLO_ERROR, etc.)
    not_found_rows = df[~df['Contact LinkedIn URL'].astype(str).str.startswith('http', na=False)].index.tolist()
    print(f"Found {len(not_found_rows)} rows to process.")
    
    if not not_found_rows:
        print("Nothing to process.")
        return

    # Initialize the browser
    # We set headless=False so the user can log in if session.json is missing
    async with BrowserManager(headless=False) as browser:
        # Load session if it exists
        if os.path.exists(SESSION_FILE):
            print(f"Loading session from {SESSION_FILE}...")
            await browser.load_session(SESSION_FILE)
        else:
            print(f"No {SESSION_FILE} found. Please log in manually in the opened browser.")
            print("After logging in, please create a dummy file named 'logged_in.txt' in this directory to continue.")
            await browser.page.goto("https://www.linkedin.com/login")
            while not os.path.exists("logged_in.txt"):
                await asyncio.sleep(2)
            os.remove("logged_in.txt") # clean up
            await browser.save_session(SESSION_FILE)
            print(f"Session saved to {SESSION_FILE}")

        scraper = PersonScraper(browser.page)
        
        # Process rows in a batch
        limit = 100 
        processed_count = 0
        
        for idx in not_found_rows:
            if processed_count >= limit:
                break
                
            row = df.loc[idx]
            name_raw = str(row['Contact Name']) if pd.notna(row['Contact Name']) else ""
            
            # Clean name (remove semicolons/emails)
            if ";" in name_raw:
                # Often it's email@co.com;Name or similar
                parts = name_raw.split(";")
                # Find the first part that doesn't look like an email
                name = ""
                for part in parts:
                    if "@" not in part and len(part.strip().split()) >= 2:
                        name = part.strip()
                        break
                if not name: name = parts[-1].strip() # Fallback
            else:
                name = name_raw
            
            company = str(row['Company name']) if pd.notna(row['Company name']) else ""
            
            if not name:
                print(f"[{processed_count+1}/{limit}] Skipping row {idx} (no name).")
                processed_count += 1
                continue
            
            print(f"[{processed_count+1}/{limit}] Finding profile for {name} ({company})...")
            
            # 1. Search for profile URL
            profile_url = await search_for_profile(browser.page, name, company)
            
            if profile_url:
                print(f"   Success: Found profile URL: {profile_url}")
                
                # 2. Update DataFrame with URL
                df.at[idx, 'Contact LinkedIn URL'] = profile_url
                df.at[idx, 'LinkedIn Confidence'] = 'found_via_scraper'
                
                # 3. Scrape profile details (DISABLED due to rate limit)
                # try:
                #     person = await scraper.scrape(profile_url)
                #     print(f"   Scraped Name: {person.name}")
                #     print(f"   Headline: {person.headline}")
                #     # Update LinkedIn Score/Confidence if needed
                #     df.at[idx, 'LinkedIn Score'] = 1.0 # Or some logic based on name match
                # except Exception as e:
                #     print(f"   Failed to scrape details for {profile_url}: {e}")
            else:
                print(f"   Failed to find profile URL for {name}.")
            
            processed_count += 1
            # Save progress periodically
            if processed_count % 5 == 0:
                df.to_excel(EXCEL_FILE, index=False)
                print("   Saved progress to Excel.")
                
            # Random sleep to avoid being flagged
            await asyncio.sleep(2)

        # Final save
        df.to_excel(EXCEL_FILE, index=False)
        print("Processing finished. Excel file updated.")

if __name__ == "__main__":
    asyncio.run(main())
