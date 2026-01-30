"""
Example script demonstrating how to upload a PDF with metadata to the API.

This shows how to send metadata along with PDF files, similar to how
JSON/text requests can include title, author, publisher, etc.
"""

import requests
from datetime import datetime

# Configuration
API_URL = "http://localhost:8000/api/incidents"
AUTH_TOKEN = "eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0..BAUYCqTHB24Kurl3.78X26PXaFRsFftms-tLMbVdJLc8-wmGKlb211lS4clU0FoXoJolLpj3NTvNcoHN-rMx6f9Qt_VL7bhFdq92Fjfe2O9gnsEaPPe1UBJ7VDHp9gZtpTNsBPtPYV5DsvyQlMcOA0qZ_0eWu2QkRLhdUYI0UXtA5NmLU0BOQW1L2pXhjmAjZNGlOngsWgfivFQX3QUCyogs9h3qHc4mlVeeYnEYgEAw4YIM.am4s1JV6IshKPijidENz0A"  # Replace with actual token
PDF_FILE_PATH = r"C:\Users\Henry\Documents\Virginia Tech\FishingProject\data\testPdfs\investigation-illegal-fishing-labour-abuse-and-hidden-ownership-uncovered-in-namibia-english.pdf"  # Replace with actual PDF path

# Metadata fields (all optional)
# NOTE: 'title' will be mapped to 'article_title' in the Source model
metadata = {
    "title": "Example Violation Report",  # Maps to article_title
    "author": "",
    "publisher": "Stop Illegal Fishing",
    "publication_date": datetime(2024, 1, 15).isoformat(),  # ISO format
    "url": "https://example.gov/reports/2024/fishing-violation-1234",
    "source_type": "News",  # Options: government, news, industry report, ngo, academic, not specified
    "status": "from_api",  # Options: extracted, from_api, user_input, modified
    "input_name": "SerpAPI",
}

# Prepare the multipart form data
with open(PDF_FILE_PATH, "rb") as pdf_file:
    files = {"file": ("document.pdf", pdf_file, "application/pdf")}

    # Add metadata as form fields
    data = {key: str(value) for key, value in metadata.items() if value is not None}

    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}

    response = requests.post(API_URL, files=files, data=data, headers=headers)

print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")

# Expected response:
# {
#     "task_id": "some-uuid",
#     "status": "pending"
# }

# Poll for task completion
if response.status_code == 202:
    task_id = response.json()["task_id"]
    task_url = f"http://localhost:8000/api/tasks/{task_id}"

    print(f"\nPolling task status at: {task_url}")

    import time

    while True:
        task_response = requests.get(task_url, headers=headers)
        task_data = task_response.json()

        print(f"Task status: {task_data['status']}")

        if task_data["status"] in ["completed", "failed"]:
            print(f"\nFinal result: {task_data}")
            break

        time.sleep(4)
