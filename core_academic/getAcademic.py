import requests
import sqlite3
from dotenv import load_dotenv
import os
import json
import time
import random

DB_PATH = "core_academic/academic.db"

load_dotenv()
API_URL = "https://api.core.ac.uk/v3/search/outputs"
apiKey = os.getenv("CORE_API_KEY")


IUU_KEYWORDS = [
    '"illegal fishing"',
    '"IUU fishing"',
    '"unreported fishing"',
    '"unregulated fishing"',
    "overfishing",
    '"illegal catch"',
    '"seafood fraud"',
    '"fishing violation"',
    '"forced labor" fishing',
    '"illegal aquaculture"',
    '"fishing sanctions"',
]


def build_query(year_after: int = 2018) -> str:
    keyword_clause = " OR ".join(f"fullText:{kw}" for kw in IUU_KEYWORDS)
    return (
        f"({keyword_clause})"
        f' AND documentType:"journal article"'
        f" AND yearPublished>{year_after}"
        f" AND _exists_:downloadUrl"
        f" AND NOT deleted:DELETED"
        f" AND NOT disabled:true"
    )


def extract_record(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "title": r.get("title"),
        "authors": [a.get("name") for a in r.get("authors") or []],
        "publishedDate": r.get("publishedDate") or r.get("yearPublished"),
        "downloadUrl": r.get("downloadUrl"),
        "sourceFulltextUrls": r.get("sourceFulltextUrls") or [],
        "fullText": r.get("fullText") or "",
    }


def init_db(path: str = DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS academic (
            id INTEGER PRIMARY KEY,
            title TEXT,
            authors TEXT,
            publishedDate TEXT,
            downloadUrl TEXT,
            sourceFulltextUrls TEXT,
            fullText TEXT
        )
    """
    )
    conn.commit()
    return conn


def insert_records(conn: sqlite3.Connection, records: list):
    rows = [
        (
            r["id"],
            r["title"],
            json.dumps(r["authors"]),
            r["publishedDate"],
            r["downloadUrl"],
            json.dumps(r["sourceFulltextUrls"]),
            r["fullText"],
        )
        for r in records
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO academic "
        "(id, title, authors, publishedDate, downloadUrl, sourceFulltextUrls, fullText) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def _get_with_retry(
    url: str,
    headers: dict,
    params: dict,
    max_retries: int = 5,
    base_delay: float = 2.0,
) -> requests.Response:
    """GET with exponential backoff on 429/500 responses."""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2**attempt) + random.uniform(0, 1)
            print(
                f"  Request error (attempt {attempt + 1}): {e}. Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)
            continue

        if response.status_code in (429, 500, 502, 503):
            if attempt == max_retries - 1:
                return response
            delay = base_delay * (2**attempt) + random.uniform(0, 1)
            print(
                f"  HTTP {response.status_code} (attempt {attempt + 1}). Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)
            continue

        return response

    return response  # type: ignore[return-value]


def search_core(max_results: int = 100, page_size: int = 25, db_path: str = DB_PATH):
    headers = {"Authorization": f"Bearer {apiKey}"}
    query = build_query()
    conn = init_db(db_path)
    total_saved = 0
    offset = 0

    try:
        while total_saved < max_results:
            print(f"Total Saved: {total_saved}/{max_results}")
            print(f"Querying Core API with offset {offset}...")
            limit = min(page_size, max_results - total_saved)
            params = {"q": query, "limit": limit, "offset": offset}

            try:
                response = _get_with_retry(API_URL, headers, params)
            except requests.exceptions.RequestException as e:
                print(f"Request failed at offset {offset}: {e}")
                break

            if response.status_code != 200:
                print(
                    f"Error {response.status_code} at offset {offset}: {response.text}"
                )

                break

            data = response.json()
            results = data.get("results") or []
            if not results:
                break

            page_records = [extract_record(r) for r in results]
            if page_records:
                insert_records(conn, page_records)
                total_saved += len(page_records)
                print(f"Saved {total_saved} records (offset {offset})")

            offset += limit
            if offset >= data.get("totalHits", 0):
                break
            time.sleep(1.0)
    finally:
        conn.close()

    return total_saved


def export_json(db_path: str = DB_PATH, json_path: str = "academic_results.json"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM academic").fetchall()
    conn.close()
    records = []
    for row in rows:
        d = dict(row)
        d["authors"] = json.loads(d["authors"]) if d["authors"] else []
        d["sourceFulltextUrls"] = (
            json.loads(d["sourceFulltextUrls"]) if d["sourceFulltextUrls"] else []
        )
        records.append(d)
    with open(json_path, "w") as f:
        json.dump(records, f, indent=2)
    return len(records)


if __name__ == "__main__":
    saved = search_core(max_results=500)
    print(f"Total saved to {DB_PATH}: {saved}")
    exported = export_json()
    print(f"Exported {exported} records to academic_results.json")
