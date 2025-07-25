from dotenv import load_dotenv
import os
import json
from external_apis import get_articles_by_date, get_all_articles_by_date


load_dotenv()

keywords = '("illegal fishing" OR "unregulated fishing" OR "unreported fishing" OR "IUU fishing" OR "pirate fishing" OR "ghost fishing" OR "fish laundering") OR (fishing AND (arrest OR seizure OR fine OR sanction OR violation OR crime OR "black market" OR "dark fleet"))'

response = get_all_articles_by_date(
    api_key=os.getenv("NEWSAPI_KEY"), keywords=keywords, from_date="2025-06-01"
)

with open("news_articles_test.json", "w") as f:
    json.dump(response, f, indent=4)
