import json
from urllib.parse import urlparse
import pandas as pd
from datetime import datetime, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
from random import shuffle

# Read the data into a pandas DataFrame
df = pd.read_csv(r"data\MergedWTP\merged_incident_data.csv")

# Convert 'Date of Incident' to datetime objects
df['Date of Incident'] = pd.to_datetime(df['Date of Incident'])


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

def is_valid_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme in ['http', 'https'], result.netloc])
    except Exception:
        return False

def is_url_active(url, session):
    """
    Checks if a given URL is accessible.
    Returns True if the URL responds with a success status code, False otherwise.
    """

    if pd.isna(url) or not isinstance(url, str) or url.strip() == '':
        return False

    url = url.strip()

    # Add scheme if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    # Validate URL structure
    if not is_valid_url(url):
        return False
    
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

def find_valid_urls(df, source_column, target_count=50, max_attempts=200, 
                   save_interval=10, save_file="url_validation_progress.json"):
    """
    Find rows with valid URLs, stopping when we reach the target count.
    Saves progress periodically and can resume from where it left off.
    
    Args:
        df: DataFrame to check
        source_column: Column containing URLs
        target_count: Number of valid URLs to find
        max_attempts: Maximum URLs to check
        save_interval: Save progress every N valid URLs found
        save_file: File to save progress to
    """
    session = setup_session()
    
    # Try to load previous progress
    progress = load_progress(save_file)
    valid_rows = progress.get('valid_rows', [])
    checked_urls = set(progress.get('checked_urls', []))
    
    # Get unique URLs to avoid duplicates
    unique_urls = df[source_column].dropna().unique()
    
    # Filter out already checked URLs
    remaining_urls = [url for url in unique_urls if url not in checked_urls]
    
    # Shuffle remaining URLs
    shuffle(remaining_urls)
    
    print(f"Starting URL validation... Target: {target_count} valid URLs")
    print(f"Already found: {len(valid_rows)} valid URLs")
    print(f"Already checked: {len(checked_urls)} URLs")
    print(f"Remaining URLs to check: {len(remaining_urls)}")
    
    checked_count = len(checked_urls)
    
    for url in remaining_urls:
        if len(valid_rows) >= target_count:
            print(f"✓ Target reached! Found {len(valid_rows)} valid URLs")
            break
        
        if checked_count >= max_attempts:
            print(f"Reached maximum attempts ({max_attempts}). Stopping.")
            break
            
        if not is_valid_url(url):
            print(f"Skipping invalid URL format: {url}")
            continue
            
        checked_count += 1
        checked_urls.add(url)
        print(f"Checking URL {checked_count}: {url[:80]}...")
        
        if is_url_active(url, session):
            # Get all rows with this URL
            matching_rows = df[df[source_column] == url]
            valid_rows.extend(matching_rows.index.tolist())
            print(f"✓ Valid! Found {len(matching_rows)} rows with this URL. Total valid rows: {len(valid_rows)}")
            
            # Save progress every save_interval valid URLs
            if len(valid_rows) % save_interval == 0:
                save_progress(save_file, valid_rows, checked_urls)
                print(f"💾 Progress saved at {len(valid_rows)} valid URLs")
        else:
            print("✗ Invalid or inaccessible")
        
        # Add a small delay to be respectful to servers
        time.sleep(0.2)
    
    # Final save
    save_progress(save_file, valid_rows, checked_urls)
    print(f"💾 Final progress saved")
    
    session.close()
    return valid_rows

def save_progress(save_file, valid_rows, checked_urls):
    """Save current progress to file"""
    progress = {
        'valid_rows': valid_rows,
        'checked_urls': list(checked_urls),
        'timestamp': time.time(),
        'total_valid': len(valid_rows),
        'total_checked': len(checked_urls)
    }
    
    try:
        with open(save_file, 'w') as f:
            json.dump(progress, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save progress: {e}")

def load_progress(save_file):
    """Load previous progress from file"""
    try:
        with open(save_file, 'r') as f:
            progress = json.load(f)
            print(f"📁 Loaded previous progress: {progress['total_valid']} valid URLs, "
                  f"{progress['total_checked']} URLs checked")
            return progress
    except FileNotFoundError:
        print("📁 No previous progress file found, starting fresh")
        return {}
    except Exception as e:
        print(f"Warning: Could not load progress: {e}")
        return {}


# Find valid URLs
print("=" * 60)
print("STARTING URL VALIDATION")
print("=" * 60)

print("Starting URL validation process...")
valid_indices = find_valid_urls(
    df, 
    'Primary Source', 
    target_count=1700, 
    max_attempts=3000,
    save_interval=25,  # Save every 50 valid URLs
    save_file="url_validation_progress.json"
)

# Create the final dataset with valid URLs
if valid_indices:
    valid_df = df.loc[valid_indices].copy()
    
    # Remove duplicates and get stats before/after
    initial_count = len(valid_df)
    valid_df = valid_df.drop_duplicates()
    final_count = len(valid_df)
    duplicates_removed = initial_count - final_count
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Found {final_count} unique rows with valid URLs")
    if duplicates_removed > 0:
        print(f"Removed {duplicates_removed} duplicate rows")
    
    # Handle date range with error checking
    try:
        date_min = valid_df['Date of Incident'].min()
        date_max = valid_df['Date of Incident'].max()
        print(f"Date range: {date_min} to {date_max}")
    except Exception as e:
        print(f"Could not determine date range: {e}")
    
    # Show sample of results
    print("\nSample of valid URLs found:")
    sample_urls = valid_df['Primary Source'].unique()[:10]
    for i, url in enumerate(sample_urls, 1):
        # Truncate very long URLs for display
        display_url = url if len(url) <= 80 else url[:77] + "..."
        print(f"{i}. {display_url}")
    
    # Save the results with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"valid_urls_sample_{timestamp}.csv"
    
    try:
        valid_df.to_csv(output_filename, index=False)
        print(f"\nResults saved to: {output_filename}")
    except Exception as e:
        print(f"Error saving to CSV: {e}")
        # Try alternative filename
        alt_filename = "valid_urls_sample_backup.csv"
        try:
            valid_df.to_csv(alt_filename, index=False)
            print(f"Results saved to backup file: {alt_filename}")
        except Exception as e2:
            print(f"Could not save results: {e2}")
    
    # Display comprehensive summary statistics
    print(f"\nSummary:")
    print(f"- Total rows with valid URLs: {final_count:,}")
    print(f"- Unique valid URLs: {len(valid_df['Primary Source'].unique()):,}")
    
    # Additional useful stats
    if 'Date of Incident' in valid_df.columns:
        try:
            date_range_str = f"{date_min.strftime('%Y-%m-%d')} to {date_max.strftime('%Y-%m-%d')}"
            print(f"- Date range: {date_range_str}")
            
            # Calculate time span
            time_span = (date_max - date_min).days
            print(f"- Time span: {time_span:,} days ({time_span/365.25:.1f} years)")
        except:
            print("- Date range: Could not calculate")
    
    # Show distribution of URLs per domain if possible
    try:
        from urllib.parse import urlparse
        domains = valid_df['Primary Source'].apply(lambda x: urlparse(str(x)).netloc)
        domain_counts = domains.value_counts()
        print(f"- Most common domains:")
        for domain, count in domain_counts.head(5).items():
            print(f"  {domain}: {count} URLs")
    except Exception as e:
        print("- Could not analyze domain distribution")
    
    # Memory usage info
    memory_mb = valid_df.memory_usage(deep=True).sum() / 1024 / 1024
    print(f"- Dataset memory usage: {memory_mb:.1f} MB")
    
else:
    print("\n" + "!" * 60)
    print("NO VALID URLS FOUND")
    print("!" * 60)
    print("Possible reasons and solutions:")
    print("1. Check if the 'Primary Source' column name is correct")
    print("2. Increase the max_attempts parameter (currently 3000)")
    print("3. Check your internet connection")
    print("4. Verify the URL format in your data")
    print("5. Check if URLs require authentication or special headers")
    print("6. Some domains might be blocking automated requests")
    
    # Show sample of URLs that were attempted
    if 'Primary Source' in df.columns:
        print(f"\nSample URLs from your data:")
        sample_urls = df['Primary Source'].dropna().head(5)
        for i, url in enumerate(sample_urls, 1):
            print(f"{i}. {url}")
    
    # Check for progress file
    try:
        import os
        if os.path.exists("url_validation_progress.json"):
            print(f"\nNote: Progress was saved to 'url_validation_progress.json'")
            print("You can resume by running the function again.")
    except:
        pass