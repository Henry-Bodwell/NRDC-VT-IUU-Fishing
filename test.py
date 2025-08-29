import requests

url = "http://localhost:8000/api/incidents"

payload = {}
files = [
    (
        "document",
        (
            "c:\\Users\\Henry\\Documents\\Virginia Tech\\FishingProject\\data\\testPdfs\\sample_non_related.pdf",
            open(
                "c:\\Users\\Henry\\Documents\\Virginia Tech\\FishingProject\\data\\testPdfs\\sample_non_related.pdf",
                "rb",
            ),
            "application/pdf",
        ),
    )
]
headers = {}
response = requests.request("GET", url, headers=headers)

print(response.text[:50])

response = requests.request("POST", url, headers=headers, data=payload, files=files)

print(response.text)
