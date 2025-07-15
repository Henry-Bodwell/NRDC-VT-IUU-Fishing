import requests
from urllib.parse import quote

def fetch_taxon_cites(taxon_name: str, page: int, api_key: str) -> dict:
    """Fetch CITES data for a given taxon name using the CITES API."""
    url = "https://api.speciesplus.net/api/v1/taxon_concepts"
    headers = {
        "X-Authentication-Token": api_key,  # Removed f-string (unnecessary)
        "Accept": "application/json"
    }
    
    params = {
        "name": taxon_name.lower().strip(),
        "with_descendants": "true",
        "page": page,
    }
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching data for {taxon_name}: {e}")
        return {}
    
def fetch_all_cites_pages(taxon_name: str, api_key: str) -> dict:
    """Fetch all CITES pages for a given taxon name."""
    CITES_ENTRIES_PER_PAGE = 500
    all_taxon_concepts = []
    total_entries = 0
    current_page = 1

    while True:
        data = fetch_taxon_cites(taxon_name, current_page, api_key)
        
        if not data or "taxon_concepts" not in data:
            print(f"No data returned for page {current_page}")
            break
        
        if current_page == 1:
            total_entries = data.get("pagination", {}).get("total_entries", 0)
            if total_entries == 0:
                print(f"No entries found for {taxon_name}.")
                break
            print(f"Total entries to fetch: {total_entries}")

        page_taxa = data.get("taxon_concepts", [])
        all_taxon_concepts.extend(page_taxa)
        print(f"Fetched page {current_page} with {len(page_taxa)} entries.")


        if len(page_taxa) < CITES_ENTRIES_PER_PAGE or len(all_taxon_concepts) >= total_entries:
            break
        current_page += 1

    merged_response = {
        "pagination": {
            "total_entries": total_entries,
            "pages_fetched": current_page,
            "per_page": CITES_ENTRIES_PER_PAGE,
            "actual_entries": len(all_taxon_concepts)  # Added for verification
        },
        "taxon_concepts": all_taxon_concepts,
    }
    print(f"Successfully merged {len(all_taxon_concepts)} taxon concepts from {current_page} pages")
    return merged_response

def fetch_iucn_red_list(taxon_rank: str, taxon_name: str, page:int, api_key: str, latest=True) -> dict:
    """Fetch IUCN Red List data for a given taxon name using the IUCN API."""
    taxon_name = taxon_name.lower().strip()
    taxon_rank = taxon_rank.lower().strip()
    url = f"https://api.iucnredlist.org/api/v4/taxa/{taxon_rank}/{taxon_name}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json"
    }
    params = {
        "page": page,
        "latest": str(latest).lower(), 
    }
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching data for {taxon_name}: {e}")
        return {}
    
def fetch_all_iucn_pages(taxon_rank: str, taxon_name: str, api_key: str) -> dict:
    """Fetch all IUCN Red List pages for a given taxon name."""
    IUCN_ENTRIES_PER_PAGE = 100
    all_assessments = []
    current_page = 1

    while True:
        data = fetch_iucn_red_list(taxon_rank, taxon_name, current_page, api_key)
        
        if not data or "assessments" not in data:
            print(f"No data returned for page {current_page}")
            break

        page_assements = data.get("assessments", [])
        all_assessments.extend(page_assements)
        print(f"Fetched page {current_page} with {len(page_assements)} entries.")

        if len(page_assements) < IUCN_ENTRIES_PER_PAGE:
            break
        current_page += 1

    merged_response = {
        "details": {
            "total_entries": len(all_assessments),
            "Taxon Rank": taxon_rank,
            "Taxon Name": taxon_name,
        },
        "result": all_assessments,
    }
    print(f"Successfully merged {len(all_assessments)} taxa from {current_page} pages")
    return merged_response

def fetch_cites_by_scientific_name(scientific_name: str, api_key: str) -> dict:
    """Fetch CITES data for a given scientific name using the CITES API."""
    scientific_name_encoded = quote(scientific_name.lower().strip())

def fetch_IUCN_by_scientific_name(scientific_name: str, api_key: str) -> dict:
    """Fetch IUCN Red List data for a given scientific name using the IUCN API."""
    scientific_name_encoded = quote(scientific_name.lower().strip())
    url = f"https://api.iucnredlist.org/api/v4/taxa/scientific_name/{scientific_name_encoded}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json"
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching data for {scientific_name}: {e}")
        return {}

def fetch_scientific_name(common_name: str) -> dict:
    """Fetch scientific name for a given common name or common name fragment."""
    common_name_encoded = quote(common_name.lower().strip())
    url = f"https://api.ncbi.nlm.nih.gov/datasets/v2/taxonomy/taxon_suggest/{common_name_encoded}"
    headers = {
        "Accept": "application/json",
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching scientific name for {common_name}: {e}")
        return {}
    
def get_name_pairs(common_name: str) -> list:
    """Fetch a list of scientific and common name pairs for a given common name fragment."""
    response = fetch_scientific_name(common_name)
    if not response:
        print(f"No data found for common name: {common_name}")
        return []
    species_list = response["sci_names_and_ids"]
    name_pairs = [(species['sci_name'], species.get('common_name')) for species in species_list]

    return name_pairs

def get_articles_by_date(api_key: str, keywords: str, from_date: str, to_date = "", page = 1) -> dict:
    """Fetch Articles from the NewsAPI by date range."""
    url = "https://newsapi.org/v2/everything?"
    headers = {
        "X-Api-Key": api_key,
        "Accept": "application/json"
    }
    if to_date != "":
        params = {
                "q": keywords,
                "from": from_date,
                "to": to_date,
                "sortBy": "relevancy",
                "pageSize": 100,
                "page": page,
            }
    else:
        params = {
                "q": keywords,
                "from": from_date,
                "sortBy": "relevancy",
                "pageSize": 100, 
                "page": page,
            }
    
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching articles: {e}")
        return {}
    
def get_all_articles_by_date(api_key: str, keywords: str, from_date: str, to_date = "") -> dict:
    """Fetch all articles by date range."""
    all_articles = []
    current_page = 1
    total_results = 0

    while True:
        data = get_articles_by_date(api_key, keywords, from_date, to_date, current_page)
        
        if not data or "articles" not in data:
            print(f"No data returned for page {current_page}")
            break
        
        if current_page == 1:
            total_results = data.get("totalResults", 0)
            if total_results == 0:
                print(f"No articles found for {keywords} from {from_date} to {to_date}.")
                break
            print(f"Total articles to fetch: {total_results}")

        page_articles = data.get("articles", [])
        all_articles.extend(page_articles)
        print(f"Fetched page {current_page} with {len(page_articles)} articles.")

        if len(page_articles) < 100 or len(all_articles) >= total_results:
            break

        with open('data/newsapi/news_articles_page_{}.json'.format(current_page), 'w') as f:
            f.write(data.get("articles", []))
            
        current_page += 1

    merged_response = {
        "pagination": {
            "total_results": total_results,
            "pages_fetched": current_page,
            "per_page": 100,
            "actual_entries": len(all_articles)  # Added for verification
        },
        "articles": all_articles,
    }
    print(f"Successfully merged {len(all_articles)} articles from {current_page} pages")
    return merged_response
    