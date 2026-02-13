import requests
from dotenv import load_dotenv
import os
import sys

load_dotenv()

BASE_URL = "https://iuudb.cs.vt.edu/api"
auth_token = os.getenv("AUTH_TOKEN")


def fetch_pdf_sources():
    """Fetch all sources with input_category = 'pdf'"""
    try:
        response = requests.get(
            f"{BASE_URL}/sources", params={"input_category": "pdf"}, timeout=30
        )
        response.raise_for_status()

        data = response.json()
        sources = data.get("sources", [])
        return sources

    except requests.exceptions.RequestException as e:
        print(f"Error fetching sources: {e}")
        sys.exit(1)


def display_sources(sources):
    """Display sources in a readable format"""
    print("\n" + "=" * 80)
    print(f"Found {len(sources)} PDF sources:")
    print("=" * 80)

    for i, source in enumerate(sources, 1):
        title = source.get("article_title", "No title")
        source_id = source.get("_id")
        url = source.get("url", "No URL")

        print(f"\n{i}. ID: {source_id}")
        print(f"   Title: {title}")
        print(f"   URL: {url}")

    print("\n" + "=" * 80)


def confirm_deletion(count):
    """Get user confirmation before deleting"""
    print(f"\n⚠️  WARNING: You are about to delete {count} PDF sources.")
    print("This action CANNOT be undone!")

    response = input("\nType 'DELETE' to confirm, or anything else to cancel: ")

    return response.strip() == "DELETE"


def delete_sources(sources):
    """Delete sources one by one"""
    deleted_count = 0
    failed_count = 0

    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    print("\nStarting deletion...")
    print("-" * 80)

    for i, source in enumerate(sources, 1):
        source_id = source.get("_id")
        title = source.get("article_title", "No title")

        try:
            response = requests.delete(
                f"{BASE_URL}/sources/{source_id}", headers=headers, timeout=30
            )

            if response.status_code == 200:
                print(f"✓ [{i}/{len(sources)}] Deleted: {title[:60]}")
                deleted_count += 1
            else:
                print(
                    f"✗ [{i}/{len(sources)}] Failed (HTTP {response.status_code}): {title[:60]}"
                )
                failed_count += 1

        except requests.exceptions.RequestException as e:
            print(f"✗ [{i}/{len(sources)}] Error: {e}")
            failed_count += 1

    print("-" * 80)
    print(f"\n✓ Successfully deleted: {deleted_count}")
    print(f"✗ Failed to delete: {failed_count}")
    print(f"Total: {len(sources)}")


def main():
    print("PDF Source Deletion Tool")
    print("=" * 80)

    # Check for auth token if needed
    if not auth_token:
        print("⚠️  Warning: No AUTH_TOKEN found in .env file")
        print("If authentication is required, this script may fail.")
        proceed = input("\nContinue anyway? (y/n): ")
        if proceed.lower() != "y":
            print("Aborted.")
            sys.exit(0)

    # Fetch PDF sources
    print("\nFetching PDF sources...")
    sources = fetch_pdf_sources()

    if not sources:
        print("No PDF sources found. Nothing to delete.")
        sys.exit(0)

    # Display sources
    display_sources(sources)

    # Get confirmation
    if not confirm_deletion(len(sources)):
        print("\n Deletion cancelled by user.")
        sys.exit(0)

    # Delete sources
    delete_sources(sources)

    print("\n Operation complete!")


if __name__ == "__main__":
    main()
