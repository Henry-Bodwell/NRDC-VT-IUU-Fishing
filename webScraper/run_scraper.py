"""
Multi-site scraper runner with configurable storage (JSON or SQLite).

This script runs searches across multiple configured sites and saves results
to either JSON files or a SQLite database with automatic deduplication.

Usage:
    # Save to JSON (default)
    python run_scraper.py --storage json --output-dir ./scraped_data

    # Save to SQLite
    python run_scraper.py --storage sqlite --db-path ./scraped_data.db

    # Scrape specific sites only
    python run_scraper.py --sites undercurrent_news oceana --storage json

    # Custom search queries
    python run_scraper.py --queries "illegal fishing" "IUU fishing" --storage sqlite
"""

import asyncio
import argparse
import logging
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from dotenv import load_dotenv

from webScraper.config.site_config import get_config_manager
from webScraper.scrapers.generic_scraper import GenericScraper
from webScraper.scrapers.sites.oceana_scraper import OceanaScraper
from webScraper.storage.json_storage import JSONStorage
from webScraper.storage.sqlite_storage import SQLiteStorage


# Default search queries for IUU fishing
DEFAULT_QUERIES = [
    "illegal fishing",
    "IUU fishing",
    "overfishing",
    "fishing violations",
    "illegal catch",
    "seafood fraud",
    "forced labor fishing",
    "illegal aquaculture",
    "illegal seafood sanctions",
]


class ScraperRunner:
    """Orchestrates scraping across multiple sites with configurable storage."""

    def __init__(
        self,
        storage_type: str = "json",
        output_dir: Path = None,
        db_path: Path = None,
        max_results_per_query: int = 10,
    ):
        """
        Initialize the scraper runner.

        Args:
            storage_type: "json" or "sqlite"
            output_dir: Directory for JSON storage (if using JSON)
            db_path: Path to SQLite database (if using SQLite)
            max_results_per_query: Maximum results to scrape per query per site
        """
        self.storage_type = storage_type
        self.max_results_per_query = max_results_per_query

        # Initialize storage
        if storage_type == "json":
            self.output_dir = output_dir or Path("./scraped_data")
            self.storage = JSONStorage(
                output_dir=self.output_dir,
                mode="single",
                filename="scraped_data.json",
                pretty_print=True,
                enable_content_hash=True,
            )
        elif storage_type == "sqlite":
            self.db_path = db_path or Path("./scraped_data.db")
            self.storage = SQLiteStorage(
                db_path=self.db_path,
                enable_fts=True,
            )
        else:
            raise ValueError(f"Unknown storage type: {storage_type}")

        # Load site configurations
        self.config_manager = get_config_manager()

        # Setup logging
        self.logger = logging.getLogger(self.__class__.__name__)

    async def scrape_site(
        self,
        site_name: str,
        queries: List[str],
    ) -> Dict[str, Any]:
        """
        Scrape a single site with multiple queries.

        Args:
            site_name: Name of the site to scrape
            queries: List of search queries

        Returns:
            Dictionary with scraping statistics
        """
        stats = {
            "site": site_name,
            "queries_attempted": 0,
            "queries_successful": 0,
            "total_results": 0,
            "saved": 0,
            "duplicates": 0,
            "errors": [],
        }

        # Get site config
        config = self.config_manager.get_config(site_name)
        if not config:
            error_msg = f"No configuration found for site: {site_name}"
            self.logger.error(error_msg)
            stats["errors"].append(error_msg)
            return stats

        self.logger.info(f"Starting scrape for {site_name} with {len(queries)} queries")

        # Create scraper instance with storage to enable URL deduplication
        # Use custom scrapers for specific sites, otherwise use GenericScraper
        if site_name == "oceana":
            scraper = OceanaScraper(storage=self.storage)
        else:
            scraper = GenericScraper(site_config=config, storage=self.storage)

        try:
            # Run each query
            for query in queries:
                stats["queries_attempted"] += 1

                try:
                    self.logger.info(f"  Query: '{query}'")

                    # Perform search
                    results = await scraper.scrape(
                        query=query,
                        max_results=self.max_results_per_query,
                    )

                    stats["total_results"] += len(results)
                    self.logger.info(f"    Found {len(results)} results")

                    # Save results with deduplication
                    if results:
                        save_stats = await self.storage.save_batch(results)
                        stats["saved"] += save_stats.get("saved", 0)
                        stats["duplicates"] += save_stats.get(
                            "duplicates_url", 0
                        ) + save_stats.get("duplicates_content", 0)

                        self.logger.info(
                            f"    Saved: {save_stats.get('saved', 0)}, "
                            f"Duplicates: {stats['duplicates']}"
                        )

                    stats["queries_successful"] += 1

                except Exception as e:
                    error_msg = f"Query '{query}' failed: {str(e)}"
                    self.logger.error(f"    {error_msg}")
                    stats["errors"].append(error_msg)

        except Exception as e:
            error_msg = f"Failed to initialize scraper for {site_name}: {str(e)}"
            self.logger.error(error_msg)
            stats["errors"].append(error_msg)

        finally:
            # Cleanup scraper
            try:
                await scraper.close()
            except Exception as e:
                self.logger.warning(f"Error during scraper cleanup: {e}")

        return stats

    async def run(
        self,
        site_names: List[str] = None,
        queries: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Run scraper across multiple sites.

        Args:
            site_names: List of site names to scrape (None = all configured sites)
            queries: List of search queries (None = use defaults)

        Returns:
            Dictionary with overall statistics
        """
        # Use all configured sites if none specified
        if not site_names:
            site_names = self.config_manager.list_sites()

        # Use default queries if none specified
        if not queries:
            queries = DEFAULT_QUERIES

        self.logger.info("Starting scraper run")
        self.logger.info(f"  Sites: {', '.join(site_names)}")
        self.logger.info(f"  Queries: {', '.join(queries)}")
        self.logger.info(f"  Storage: {self.storage_type}")

        start_time = datetime.now()

        # Overall statistics
        overall_stats = {
            "start_time": start_time.isoformat(),
            "sites_attempted": len(site_names),
            "sites_successful": 0,
            "total_results": 0,
            "total_saved": 0,
            "total_duplicates": 0,
            "site_stats": [],
            "errors": [],
        }

        # Scrape each site sequentially (to avoid overwhelming sites)
        for site_name in site_names:
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"Scraping site: {site_name}")
            self.logger.info(f"{'='*60}")

            site_stats = await self.scrape_site(site_name, queries)

            overall_stats["site_stats"].append(site_stats)
            overall_stats["total_results"] += site_stats["total_results"]
            overall_stats["total_saved"] += site_stats["saved"]
            overall_stats["total_duplicates"] += site_stats["duplicates"]

            if site_stats["queries_successful"] > 0:
                overall_stats["sites_successful"] += 1

            if site_stats["errors"]:
                overall_stats["errors"].extend(site_stats["errors"])

        # Finalize
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        overall_stats["end_time"] = end_time.isoformat()
        overall_stats["duration_seconds"] = duration

        # Close storage
        await self.storage.close()

        # Print summary
        self.print_summary(overall_stats)

        return overall_stats

    def print_summary(self, stats: Dict[str, Any]) -> None:
        """Print a summary of scraping results."""
        print("\n" + "=" * 60)
        print("SCRAPING SUMMARY")
        print("=" * 60)
        print(f"Duration: {stats['duration_seconds']:.1f} seconds")
        print(f"Sites attempted: {stats['sites_attempted']}")
        print(f"Sites successful: {stats['sites_successful']}")
        print(f"Total results found: {stats['total_results']}")
        print(f"New items saved: {stats['total_saved']}")
        print(f"Duplicates skipped: {stats['total_duplicates']}")

        if self.storage_type == "json":
            print(f"\nOutput location: {self.output_dir / 'scraped_data.json'}")
        else:
            print(f"\nDatabase location: {self.db_path}")

        print("\nPer-site breakdown:")
        for site_stat in stats["site_stats"]:
            print(f"\n  {site_stat['site']}:")
            print(
                f"    Queries: {site_stat['queries_successful']}/{site_stat['queries_attempted']}"
            )
            print(f"    Results: {site_stat['total_results']}")
            print(f"    Saved: {site_stat['saved']}")
            print(f"    Duplicates: {site_stat['duplicates']}")

            if site_stat["errors"]:
                print(f"    Errors: {len(site_stat['errors'])}")

        if stats["errors"]:
            print(f"\n⚠ Total errors: {len(stats['errors'])}")
            print("\nFirst few errors:")
            for error in stats["errors"][:5]:
                print(f"  - {error}")


async def main():
    """Main entry point."""
    # Load environment variables
    load_dotenv()

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Run web scraper across multiple configured sites",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--storage",
        choices=["json", "sqlite"],
        default="json",
        help="Storage backend to use (default: json)",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./scraped_data"),
        help="Output directory for JSON storage (default: ./scraped_data)",
    )

    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("./scraped_data.db"),
        help="Database path for SQLite storage (default: ./scraped_data.db)",
    )

    parser.add_argument(
        "--sites",
        nargs="+",
        help="Specific sites to scrape (default: all configured sites)",
    )

    parser.add_argument(
        "--queries",
        nargs="+",
        help="Search queries to use (default: predefined IUU fishing queries)",
    )

    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum results per query per site (default: 10)",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Create runner
    runner = ScraperRunner(
        storage_type=args.storage,
        output_dir=args.output_dir,
        db_path=args.db_path,
        max_results_per_query=args.max_results,
    )

    # Run scraper
    try:
        await runner.run(
            site_names=args.sites,
            queries=args.queries,
        )
    except KeyboardInterrupt:
        print("\n\nScraping interrupted by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
