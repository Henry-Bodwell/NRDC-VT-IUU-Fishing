import os
from dotenv import load_dotenv
import json
import external_apis as fn
import pandas as pd

load_dotenv()

cites_api_key = os.getenv("CITES_API_KEY")
if not cites_api_key:
    raise ValueError(
        "CITES_API_KEY not found in environment variables. Please set it in your .env file."
    )

iucn_api_key = os.getenv("IUCN_API_KEY")
if not iucn_api_key:
    raise ValueError(
        "IUCN_API_KEY not found in environment variables. Please set it in your .env file."
    )

lowest_classification = pd.read_csv("test.csv")

for index, row in lowest_classification.iterrows():
    taxon_name = row["name"]
    taxon_rank = row["level"]

    response = fn.fetch_all_cites_pages(taxon_name, cites_api_key)
    if response:
        with open(f"cites_{taxon_name}.json", "w") as f:
            json.dump(response, f, indent=4)
        print(f"Data for '{taxon_name}' saved to cites_{taxon_name}.json")

    response = fn.fetch_all_iucn_pages(taxon_rank, taxon_name, iucn_api_key)
    if response:
        with open(f"iucn_{taxon_name}.json", "w") as f:
            json.dump(response, f, indent=4)
        print(f"Data for '{taxon_name}' saved to iucn_{taxon_name}.json")
