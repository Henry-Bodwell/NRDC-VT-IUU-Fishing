#!/usr/bin/env python
"""
Test script to verify all webScraper imports are working correctly.
"""


def test_imports():
    """Test all major imports from the webScraper module."""
    print("Testing webScraper imports...\n")

    # Test main package imports
    print("1. Testing main package imports...")
    try:
        from webScraper import (
            scrape_site,
            GenericScraper,
            BaseScraper,
            get_site_config,
            get_config_manager,
        )

        print("   ✓ Main package imports successful")
    except ImportError as e:
        print(f"   ✗ Main package imports failed: {e}")
        return False

    # Test config imports
    print("\n2. Testing config imports...")
    try:
        from webScraper.config import (
            get_settings,
            SiteConfig,
            SelectorConfig,
            RateLimitConfig,
            PaginationConfig,
        )

        print("   ✓ Config imports successful")
    except ImportError as e:
        print(f"   ✗ Config imports failed: {e}")
        return False

    # Test scraper imports
    print("\n3. Testing scraper imports...")
    try:
        from webScraper.scrapers import (
            BaseScraper,
            GenericScraper,
            ScraperStatus,
            SearchResult,
            ScrapedContent,
        )

        print("   ✓ Scraper imports successful")
    except ImportError as e:
        print(f"   ✗ Scraper imports failed: {e}")
        return False

    # Test utility imports
    print("\n4. Testing utility imports...")
    try:
        from webScraper.utils import ConfigBuilder, ConfigTester

        print("   ✓ Utility imports successful")
    except ImportError as e:
        print(f"   ✗ Utility imports failed: {e}")
        return False

    # Test configuration loading
    print("\n5. Testing configuration loading...")
    try:
        from webScraper.config import get_config_manager, get_site_config

        manager = get_config_manager()
        sites = manager.list_sites()
        print(f"   ✓ Found {len(sites)} configured sites: {sites}")

        if sites:
            config = get_site_config(sites[0])
            print(f"   ✓ Successfully loaded config: {config.site_name}")
        else:
            print("   ⚠ No site configurations found")
    except Exception as e:
        print(f"   ✗ Configuration loading failed: {e}")
        return False

    print("\n" + "=" * 60)
    print("✓ All imports successful! webScraper module is ready to use.")
    print("=" * 60)
    return True


if __name__ == "__main__":
    import sys

    success = test_imports()
    sys.exit(0 if success else 1)
