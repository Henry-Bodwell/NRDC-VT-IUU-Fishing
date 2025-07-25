import os
from dotenv import load_dotenv
import json
import newsAnalysisTool as ws

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
scraper = ws.NewsAnalysisTool(model="openai/gpt-4o-mini", api_key=api_key)

results = scraper.extract_from_url(
    r"https://cbcgdf.wordpress.com/2024/08/07/beijing-customs-intercepted-at-the-capital-airport-a-box-of-oahu-tree-snail-shells-cbcgdf-expert-shen-yihang-reports/"
)

resultsJSON = scraper.format_results(results)

with open("dbHeadersTest.json", "w") as f:
    json.dump(resultsJSON, f, indent=4)
