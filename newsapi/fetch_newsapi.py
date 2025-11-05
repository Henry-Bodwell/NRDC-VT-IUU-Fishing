import argparse
import itertools
import json
import os
import random
import sqlite3
import sys
import arrow

from pathlib import Path
from dotenv import load_dotenv

from eventregistry import *


class NewsapiFetcher:

    def __init__(self, api_key, start_date, end_date=None, outfile="", concepts=None):
        self.results = set()

        self.er = EventRegistry(apiKey=api_key, allowUseOfArchive=True)
        self.start_date = start_date
        self.end_date = (
            end_date
            if end_date is not None
            else arrow.now().shift(days=-1).isoformat()[:10]
        )
        self.concepts = concepts if concepts else self.get_default_iuu_concepts()
        self.outfile = outfile if outfile else f"{start_date}_to_{self.end_date}_iuu_fishing"
        self.cache = {}
        self.root = "data/newsapi/v0.1_raw"

    def get_default_iuu_concepts(self):
        """
        Returns default complex query for IUU fishing-related topics.

        This returns an EventRegistry CombinedQuery object for comprehensive
        IUU fishing coverage:
        - Direct IUU concepts (illegal fishing, seafood mislabeling)
        - Labor violations + seafood context + enforcement

        If users provide their own concepts via --concepts, those will be used instead
        in a simple OR query.
        """
        # Build the complex query using EventRegistry objects
        # Top level: (IUU Fishing) OR (Seafood Mislabeling) OR (Labor + Context + Enforcement)

        return CombinedQuery.OR(
            [
                # Direct IUU fishing
                BaseQuery(
                    conceptUri="http://en.wikipedia.org/wiki/Illegal,_unreported_and_unregulated_fishing"
                ),
                # Seafood mislabeling
                BaseQuery(
                    conceptUri="http://en.wikipedia.org/wiki/Seafood_mislabelling"
                ),
                # Labor violations + seafood context + enforcement actions
                CombinedQuery.AND(
                    [
                        # Labor/sanctions issues
                        CombinedQuery.OR(
                            [
                                BaseQuery(
                                    conceptUri="http://en.wikipedia.org/wiki/Transshipment"
                                ),
                                BaseQuery(
                                    conceptUri="http://en.wikipedia.org/wiki/Sanctions_(law)"
                                ),
                                BaseQuery(
                                    conceptUri="http://en.wikipedia.org/wiki/Unfree_labour"
                                ),
                                BaseQuery(
                                    conceptUri="http://en.wikipedia.org/wiki/Workplace_violence"
                                ),
                                BaseQuery(
                                    conceptUri="http://en.wikipedia.org/wiki/Wage_theft"
                                ),
                            ]
                        ),
                        # Maritime/seafood context
                        CombinedQuery.OR(
                            [
                                BaseQuery(
                                    conceptUri="http://en.wikipedia.org/wiki/Ship"
                                ),
                                BaseQuery(
                                    conceptUri="http://en.wikipedia.org/wiki/Seafood"
                                ),
                                BaseQuery(
                                    conceptUri="http://en.wikipedia.org/wiki/Fish"
                                ),
                            ]
                        ),
                        # Enforcement actions
                        CombinedQuery.OR(
                            [
                                BaseQuery(
                                    conceptUri="http://en.wikipedia.org/wiki/Arrest"
                                ),
                                BaseQuery(
                                    conceptUri="http://en.wikipedia.org/wiki/Criminal_investigation"
                                ),
                                BaseQuery(
                                    conceptUri="http://en.wikipedia.org/wiki/Indictment"
                                ),
                                BaseQuery(
                                    conceptUri="http://en.wikipedia.org/wiki/Search_and_seizure"
                                ),
                                BaseQuery(
                                    conceptUri="http://en.wikipedia.org/wiki/Fine_(penalty)"
                                ),
                            ]
                        ),
                    ]
                ),
            ]
        )

    def open_file(self, filename):
        if filename in self.cache:
            return self.cache[filename]

        dir_path = Path(os.path.dirname(filename))
        if not dir_path.is_dir():
            dir_path.mkdir(parents=True, exist_ok=True)

        self.cache[filename] = open(filename, "a")
        return self.cache[filename]

    def fetch_newsapi(self):
        """
        Fetches article URIs based on concepts or default complex query.
        Phase 1: Get all URIs (lightweight queries)

        Handles two modes:
        1. User-provided concepts (list): Simple OR query with date range
        2. Default complex query (CombinedQuery): Uses the nested query structure directly
        """
        # Check if concepts is a CombinedQuery (default complex query) or list (user concepts)
        if isinstance(self.concepts, CombinedQuery):
            # Default complex query - wrap with date range
            print("Using default IUU fishing complex query")

            # Wrap the combined query with ComplexArticleQuery and add date range
            cq = ComplexArticleQuery(
                query=CombinedQuery.AND(
                    [
                        self.concepts,
                        BaseQuery(dateStart=self.start_date, dateEnd=self.end_date),
                    ]
                ),
                isDuplicateFilter="skipDuplicates"
            )

            self.fetchURIs(cq, "default_complex_query")

        elif isinstance(self.concepts, list):
            # User-provided concept list - simple OR query for each
            print(f"Using {len(self.concepts)} user-provided concepts")

            for i, concept_uri in enumerate(self.concepts):
                print(f"Fetching concept {i+1}/{len(self.concepts)}: {concept_uri}")

                # Build simple query for this concept with date range
                cq = ComplexArticleQuery(
                    BaseQuery(
                        conceptUri=concept_uri,
                        dateStart=self.start_date,
                        dateEnd=self.end_date,
                    ),
                    isDuplicateFilter="skipDuplicates"
                )

                self.fetchURIs(cq, f"concept_{i}")
        else:
            raise ValueError(
                f"concepts must be CombinedQuery or list, got {type(self.concepts)}"
            )

        # Save deduplicated URI list
        # Replace colons in timestamp for Windows compatibility
        timestamp = arrow.now().format("YYYY-MM-DD_HH-mm-ss")
        filename = f"data/newsapi/{self.outfile}_{timestamp}_uris.json"
        dir_path = Path(os.path.dirname(filename))
        if not dir_path.is_dir():
            dir_path.mkdir(parents=True, exist_ok=True)

        with open(filename, "w") as f:
            output_data = {
                "uris": list(self.results),
                "date_range": {"start": self.start_date, "end": self.end_date},
                "total_count": len(self.results),
            }

            # Store query info based on type
            if isinstance(self.concepts, CombinedQuery):
                output_data["query_type"] = "complex"
                output_data["query"] = "default_iuu_fishing_query"
            else:
                output_data["query_type"] = "simple"
                output_data["concepts"] = self.concepts

            json.dump(output_data, f, indent=2)
            print(f"{len(self.results)} unique uris written to {filename}")

    def fetchURIs(self, cq, log_identifier):
        page = 1
        totalPages = 1

        while page <= totalPages:
            print(f"PAGE {page} {log_identifier} *********")

            query = QueryArticles.initWithComplexQuery(cq)
            query.setRequestedResult(
                RequestArticlesUriWgtList(page=page, count=50000)
            )

            print(query._getQueryParams())
            res = self.er.execQuery(query)

            # res is a json-able dict
            # Replace colons in timestamp for Windows compatibility
            timestamp = arrow.now().format("YYYY-MM-DD_HH-mm-ss")
            filename = f"data/newsapi/sets/{timestamp}.json"

            # Create directory if it doesn't exist
            dir_path = Path(os.path.dirname(filename))
            if not dir_path.is_dir():
                dir_path.mkdir(parents=True, exist_ok=True)

            with open(filename, "w") as f:
                json.dump(res, f)

            uriList = self.er.getUriFromUriWgt(
                res.get("uriWgtList", {}).get("results", [])
            )

            print(f"results from this page {len(uriList)}")
            if len(uriList) == 0:
                print(res)
                # print(0/0)

            before = len(self.results)

            # Add this page to actual results
            self.results = self.results.union(uriList)

            print(f"number added to results {len(self.results) - before}")

            totalPages = res.get("uriWgtList", {}).get("pages", 1)
            page += 1
            print(f"{page} < {totalPages} total")

    def fetch_articles(self, uriList):
        con = sqlite3.connect("data/newsapi.db")
        cur = con.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                uri TEXT PRIMARY KEY,
                filepath TEXT,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed BOOLEAN DEFAULT 0,
                processed_at TIMESTAMP,
                processing_error TEXT
            )
        """
        )

        cur.execute(f"select uri from articles")
        matches = cur.fetchall()
        have = set(itertools.chain.from_iterable(matches))

        neededUris = sorted(list(set(uriList) - set(have)))

        page_size = 100
        # for i in range(0, len(uriList), page_size):
        #     batch = uriList[i:i+page_size]

        #     in_clause = ", ".join([f"'{uri}'" for uri in uriList])
        #     cur.execute(f"select uri from articles where uri in ({in_clause})")
        #     matches = cur.fetchall()

        #     batch = set(batch) - set(set(itertools.chain.from_iterable(matches)))
        #     neededUris.extend(batch)

        print(f"Need {len(neededUris)} of {len(uriList)} total uris")

        for i in range(0, len(neededUris), page_size):
            batch = neededUris[i : i + page_size]

            q = QueryArticle(batch)
            arts = self.er.execQuery(q)

            print(f"Writing articles")

            for art in [val.get("info") for val in arts.values() if "info" in val]:
                date = arrow.get(art["date"])
                filename = os.path.join(
                    self.root,
                    date.format("YYYY"),
                    date.format("MM"),
                    f"{date.format('DD')}.json",
                )

                f = self.open_file(filename)
                f.write(json.dumps(art))
                f.write("\n")

                cur.execute(
                    "INSERT INTO articles (uri, filepath) VALUES (?, ?)",
                    (art["uri"], filename)
                )
            con.commit()

        con.close()

    @staticmethod
    def get_unprocessed_articles(limit=None, db_path="data/newsapi.db"):
        """
        Get articles that haven't been processed through the pipeline yet.

        Args:
            limit: Maximum number of articles to return (None for all)
            db_path: Path to SQLite database

        Returns:
            List of dicts with 'uri', 'filepath', and full article data
        """
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row  # Return rows as dicts
        cur = con.cursor()

        query = "SELECT uri, filepath FROM articles WHERE processed = 0 OR processed IS NULL"
        if limit:
            query += f" LIMIT {limit}"

        cur.execute(query)
        rows = cur.fetchall()
        con.close()

        articles = []
        for row in rows:
            # Read the article from the JSON file
            article_data = NewsapiFetcher._read_article_from_file(
                row["filepath"], row["uri"]
            )
            if article_data:
                articles.append(
                    {
                        "uri": row["uri"],
                        "filepath": row["filepath"],
                        "article": article_data,
                    }
                )

        return articles

    @staticmethod
    def _read_article_from_file(filepath, uri):
        """Read a specific article from a newline-delimited JSON file."""
        try:
            with open(filepath, "r") as f:
                for line in f:
                    article = json.loads(line)
                    if article.get("uri") == uri:
                        return article
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error reading article {uri} from {filepath}: {e}")
            return None

    @staticmethod
    def mark_processed(uri, success=True, error_msg=None, db_path="data/newsapi.db"):
        """
        Mark an article as processed.

        Args:
            uri: Article URI
            success: Whether processing succeeded
            error_msg: Error message if processing failed
            db_path: Path to SQLite database
        """
        con = sqlite3.connect(db_path)
        cur = con.cursor()

        cur.execute(
            """
            UPDATE articles
            SET processed = ?,
                processed_at = CURRENT_TIMESTAMP,
                processing_error = ?
            WHERE uri = ?
        """,
            (1 if success else 0, error_msg, uri),
        )

        con.commit()
        con.close()

    @staticmethod
    def get_processing_stats(db_path="data/newsapi.db"):
        """Get statistics on article processing."""
        con = sqlite3.connect(db_path)
        cur = con.cursor()

        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN processed = 1 THEN 1 ELSE 0 END) as processed,
                SUM(CASE WHEN processed = 0 OR processed IS NULL THEN 1 ELSE 0 END) as unprocessed,
                SUM(CASE WHEN processing_error IS NOT NULL THEN 1 ELSE 0 END) as errors
            FROM articles
        """
        )

        result = cur.fetchone()
        con.close()

        return {
            "total": result[0],
            "processed": result[1] or 0,
            "unprocessed": result[2] or 0,
            "errors": result[3] or 0,
        }


if __name__ == "__main__":
    # Load environment variables from .env file
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Fetch IUU fishing news articles from EventRegistry"
    )
    parser.add_argument(
        "--api-key",
        help="EventRegistry API key (falls back to EVENTREGISTRY_API_KEY env var)"
    )
    parser.add_argument(
        "--start-date", required=True, help="Start date in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--end-date", help="End date in YYYY-MM-DD format (defaults to yesterday)"
    )
    parser.add_argument(
        "--concepts", nargs="+", help="List of EventRegistry concept URIs to search"
    )
    parser.add_argument(
        "--outfile", help="Output file prefix (defaults to date_iuu_fishing)"
    )
    parser.add_argument(
        "--fetch-articles",
        action="store_true",
        help="Also fetch full article content (not just URIs)",
    )
    parser.add_argument(
        "--uri-file",
        help="JSON file containing URIs to fetch articles for (skips URI fetching)",
    )

    args = parser.parse_args()

    # Get API key from args or environment variable
    api_key = args.api_key or os.getenv("EVENTREGISTRY_API_KEY")
    if not api_key:
        parser.error("--api-key is required or EVENTREGISTRY_API_KEY must be set in .env file")

    # Initialize fetcher
    fetcher = NewsapiFetcher(
        api_key=api_key,
        start_date=args.start_date,
        end_date=args.end_date,
        outfile=args.outfile,
        concepts=args.concepts,
    )

    # Fetch URIs unless loading from file
    if args.uri_file:
        print(f"Loading URIs from {args.uri_file}")
        with open(args.uri_file, "r") as f:
            data = json.load(f)
            fetcher.results = set(data["uris"])
    else:
        print(f"Fetching URIs for concepts: {fetcher.concepts}")
        fetcher.fetch_newsapi()

    # Optionally fetch full articles
    if args.fetch_articles:
        print(f"Fetching full articles for {len(fetcher.results)} URIs")
        fetcher.fetch_articles(list(fetcher.results))
