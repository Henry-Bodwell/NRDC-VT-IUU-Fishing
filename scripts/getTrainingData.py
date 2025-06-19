import pandas as pd
from datetime import datetime, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import random

# Read the data into a pandas DataFrame
df = pd.read_csv(r"data\MergedWTP\merged_incident_data.csv")

# Convert 'Date of Incident' to datetime objects
df['Date of Incident'] = pd.to_datetime(df['Date of Incident'])

# Define the current date as June 18, 2025
current_date = datetime(2025, 6, 18)
three_years_ago = current_date - timedelta(days=1*365)

# Filter the DataFrame to include only incidents within the last 3 years
filtered_df = df[df['Date of Incident'] >= three_years_ago].copy()
filtered_df.reset_index(drop=True, inplace=True)

def setup_session():
    """
    Set up a requests session with retry strategy and proper headers
    """
    session = requests.Session()
    
    # Define retry strategy
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Add headers to appear more like a regular browser
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })
    
    return session

def is_url_active(url, session):
    """
    Checks if a given URL is accessible.
    Returns True if the URL responds with a success status code, False otherwise.
    """
    if pd.isna(url) or not isinstance(url, str) or url.strip() == '':
        return False
    
    # Clean the URL
    url = url.strip()
    
    # Add protocol if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    try:
        response = session.head(url, timeout=15, allow_redirects=True)
        # Consider 2xx and 3xx status codes as active
        if response.status_code < 400:
            return True
        
        # If HEAD fails, try GET (some servers don't support HEAD)
        response = session.get(url, timeout=15, allow_redirects=True)
        return response.status_code < 400
        
    except requests.RequestException as e:
        print(f"Error checking URL {url}: {type(e).__name__}")
        return False

def find_valid_urls(df, source_column, target_count=50, max_attempts=200):
    """
    Find rows with valid URLs, stopping when we reach the target count
    """
    session = setup_session()
    valid_rows = []
    checked_count = 0
    
    # Get unique URLs to avoid duplicates
    unique_urls = df[source_column].dropna().unique()
    
    # Shuffle to get a random sample
    random.shuffle(unique_urls)
    
    print(f"Starting URL validation... Target: {target_count} valid URLs")
    print(f"Total unique URLs to check: {len(unique_urls)}")
    
    for url in unique_urls:
        if len(valid_rows) >= target_count:
            break
        
        if checked_count >= max_attempts:
            print(f"Reached maximum attempts ({max_attempts}). Stopping.")
            break
            
        checked_count += 1
        print(f"Checking URL {checked_count}: {url[:80]}...")
        
        if is_url_active(url, session):
            # Get all rows with this URL
            matching_rows = df[df[source_column] == url]
            valid_rows.extend(matching_rows.index.tolist())
            print(f"✓ Valid! Found {len(matching_rows)} rows with this URL. Total valid rows: {len(valid_rows)}")
        else:
            print("✗ Invalid or inaccessible")
        
        # Add a small delay to be respectful to servers
        time.sleep(0.5)
    
    session.close()
    return valid_rows

# Find valid URLs
print("=" * 60)
print("STARTING URL VALIDATION")
print("=" * 60)

valid_indices = find_valid_urls(filtered_df, 'Primary Source', target_count=50, max_attempts=200)

# Create the final dataset with valid URLs
if valid_indices:
    valid_df = filtered_df.loc[valid_indices].copy()
    valid_df = valid_df.drop_duplicates()  # Remove any duplicates
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Found {len(valid_df)} rows with valid URLs")
    print(f"Date range: {valid_df['Date of Incident'].min()} to {valid_df['Date of Incident'].max()}")
    
    # Show sample of results
    print("\nSample of valid URLs found:")
    sample_urls = valid_df['Primary Source'].unique()[:10]
    for i, url in enumerate(sample_urls, 1):
        print(f"{i}. {url}")
    
    # Save the results
    output_filename = "valid_urls_sample.csv"
    valid_df.to_csv(output_filename, index=False)
    print(f"\nResults saved to: {output_filename}")
    
    # Display summary statistics
    print(f"\nSummary:")
    print(f"- Total rows with valid URLs: {len(valid_df)}")
    print(f"- Unique valid URLs: {len(valid_df['Primary Source'].unique())}")
    print(f"- Date range: {valid_df['Date of Incident'].min().strftime('%Y-%m-%d')} to {valid_df['Date of Incident'].max().strftime('%Y-%m-%d')}")
    
else:
    print("No valid URLs found. You may need to:")
    print("1. Check if the 'Primary Source' column name is correct")
    print("2. Increase the max_attempts parameter")
    print("3. Check your internet connection")
    print("4. Verify the URL format in your data")