import functions as fn
import os
from dotenv import load_dotenv
import json

load_dotenv()


api_key = os.getenv("NIH_API_KEY")
if not api_key:
    raise ValueError("NIH_API_KEY not found in environment variables. Please set it in your .env file.")

response = fn.fetch_scientific_name("Salmon", api_key)
print(response)