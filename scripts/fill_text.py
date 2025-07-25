import pandas as pd
import time
from urllib.parse import urlparse
from webscraper import ScraperFactory # Assuming this is your file with the scraper code

# --- Configuration ---
# 1. Add domains you want to skip to this set.
BLACKLISTED_DOMAINS = {'twitter.com', 'linkedin.com'}

# 2. Set a pause duration in seconds between each request.
PAUSE_PER_REQUEST = 0.5 

def scrape_url_text(url: str) -> str:
    """
    A wrapper function to scrape a single URL with a pause and blacklist check.
    Handles errors and returns scraped text or an empty string.
    """
    time.sleep(PAUSE_PER_REQUEST)

    if not isinstance(url, str) or not url.startswith('http'):
        print(f"Skipping invalid URL: {url}")
        return ""

    try:
        domain = urlparse(url).netloc
        if domain in BLACKLISTED_DOMAINS:
            print(f"Skipping blacklisted domain: {domain}")
            return "BLACKLISTED" # Return a specific marker for clarity
    except Exception:
        print(f"Could not parse URL to check domain: {url}")
        return "INVALID_URL"

    # --- Proceed with scraping if not blacklisted ---
    try:
        # Use the factory to get the correct scraper for the url
        scraper = ScraperFactory.create_scraper(url)
        text = scraper.scrape_article(url)
        return text
    except Exception as e:
        print(f"An unexpected error occurred for URL {url}: {e}")
        return "SCRAPING_FAILED"

# 1. Read your CSV file
df = pd.read_csv('valid_urls_sample_20250722_200059.csv')

# 2. Apply the scraping function to the 'url' column
#    This creates a new column named 'scraped_text'
try:
    print("Starting to scrape URLs...")
    df['scraped_text'] = df['Primary Source'].apply(scrape_url_text)
    print("Scraping complete.")

# 3. Save the results to a new CSV file
finally:
    # This finally block ensures your progress is saved even if the script is interrupted
    print("Saving progress to urls_with_text.csv...")
    df.to_csv('traffic_urls_with_text.csv', index=False)

print("Successfully saved results to urls_with_text.csv")


