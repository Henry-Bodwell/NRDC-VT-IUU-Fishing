"""
Configuration testing and validation utility.

This script helps test site configurations to ensure selectors work correctly
before running full scraping operations.
"""

import asyncio
from typing import Dict
from playwright.async_api import async_playwright
from webScraper.config.site_config import get_site_config, get_config_manager


class ConfigTester:
    """Test and validate site configurations."""

    def __init__(self, headless: bool = False):
        """
        Initialize the config tester.

        Args:
            headless: Run browser in headless mode (False for debugging)
        """
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def __aenter__(self):
        """Async context manager entry."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def test_configuration(
        self, site_name: str, test_query: str = "test"
    ) -> Dict[str, any]:
        """
        Test a site configuration.

        Args:
            site_name: Name of the site configuration to test
            test_query: Query to use for testing

        Returns:
            Dictionary with test results
        """
        config = get_site_config(site_name)
        if not config:
            return {"success": False, "error": f"Configuration not found: {site_name}"}

        results = {"site_name": site_name, "success": True, "tests": {}}

        print(f"\n{'='*60}")
        print(f"Testing configuration: {site_name}")
        print(f"Base URL: {config.base_url}")
        print(f"{'='*60}\n")

        # Test 1: Load search page
        print("Test 1: Loading search page...")
        try:
            await self.page.goto(config.search_url)
            await self.page.wait_for_load_state("networkidle")
            results["tests"]["search_page_load"] = {
                "success": True,
                "url": self.page.url,
            }
            print(f"  ✓ Search page loaded: {self.page.url}")
        except Exception as e:
            results["tests"]["search_page_load"] = {"success": False, "error": str(e)}
            results["success"] = False
            print(f"  ✗ Failed to load search page: {e}")
            return results

        # Test 2: Find search input
        print("\nTest 2: Finding search input...")
        try:
            input_element = await self.page.query_selector(
                config.selectors.search_input
            )
            if input_element:
                results["tests"]["search_input"] = {"success": True}
                print(f"  ✓ Found search input: {config.selectors.search_input}")
            else:
                results["tests"]["search_input"] = {
                    "success": False,
                    "error": "Element not found",
                }
                results["success"] = False
                print(f"  ✗ Search input not found: {config.selectors.search_input}")
        except Exception as e:
            results["tests"]["search_input"] = {"success": False, "error": str(e)}
            results["success"] = False
            print(f"  ✗ Error finding search input: {e}")

        # Test 3: Find search button
        print("\nTest 3: Finding search button...")
        try:
            button_element = await self.page.query_selector(
                config.selectors.search_button
            )
            if button_element:
                results["tests"]["search_button"] = {"success": True}
                print(f"  ✓ Found search button: {config.selectors.search_button}")
            else:
                results["tests"]["search_button"] = {
                    "success": False,
                    "error": "Element not found",
                }
                results["success"] = False
                print(f"  ✗ Search button not found: {config.selectors.search_button}")
        except Exception as e:
            results["tests"]["search_button"] = {"success": False, "error": str(e)}
            results["success"] = False
            print(f"  ✗ Error finding search button: {e}")

        # Test 4: Submit search query
        print(f"\nTest 4: Submitting test query '{test_query}'...")
        try:
            await self.page.fill(config.selectors.search_input, test_query)
            await self.page.click(config.selectors.search_button)

            # Wait for results
            wait_selector = config.wait_for_selector or config.selectors.result_links
            await self.page.wait_for_selector(
                wait_selector, state="visible", timeout=config.wait_for_timeout
            )

            results["tests"]["submit_query"] = {"success": True}
            print("  ✓ Successfully submitted query and loaded results")
        except Exception as e:
            results["tests"]["submit_query"] = {"success": False, "error": str(e)}
            results["success"] = False
            print(f"  ✗ Failed to submit query: {e}")
            return results

        # Test 5: Extract result links
        print("\nTest 5: Extracting result links...")
        try:
            result_elements = await self.page.query_selector_all(
                config.selectors.result_links
            )
            count = len(result_elements)

            if count > 0:
                results["tests"]["result_links"] = {"success": True, "count": count}
                print(
                    f"  ✓ Found {count} result links: {config.selectors.result_links}"
                )

                # Show first few URLs
                sample_urls = []
                for i, element in enumerate(result_elements[:3]):
                    url = await element.get_attribute("href")
                    sample_urls.append(url)
                    print(f"    Sample {i+1}: {url}")

                results["tests"]["result_links"]["sample_urls"] = sample_urls
            else:
                results["tests"]["result_links"] = {
                    "success": False,
                    "error": "No results found",
                }
                results["success"] = False
                print(f"  ✗ No result links found: {config.selectors.result_links}")
        except Exception as e:
            results["tests"]["result_links"] = {"success": False, "error": str(e)}
            results["success"] = False
            print(f"  ✗ Error extracting result links: {e}")

        # Test 6: Check optional selectors (result title, snippet)
        if config.selectors.result_title:
            print("\nTest 6a: Finding result titles...")
            try:
                title_elements = await self.page.query_selector_all(
                    config.selectors.result_title
                )
                count = len(title_elements)
                results["tests"]["result_title"] = {
                    "success": count > 0,
                    "count": count,
                }
                if count > 0:
                    print(f"  ✓ Found {count} result titles")
                else:
                    print("  ⚠ No result titles found (optional)")
            except Exception as e:
                results["tests"]["result_title"] = {"success": False, "error": str(e)}
                print(f"  ⚠ Error finding result titles: {e}")

        if config.selectors.result_snippet:
            print("\nTest 6b: Finding result snippets...")
            try:
                snippet_elements = await self.page.query_selector_all(
                    config.selectors.result_snippet
                )
                count = len(snippet_elements)
                results["tests"]["result_snippet"] = {
                    "success": count > 0,
                    "count": count,
                }
                if count > 0:
                    print(f"  ✓ Found {count} result snippets")
                else:
                    print("  ⚠ No result snippets found (optional)")
            except Exception as e:
                results["tests"]["result_snippet"] = {"success": False, "error": str(e)}
                print(f"  ⚠ Error finding result snippets: {e}")

        # Test 7: Check pagination
        if config.pagination.enabled and config.pagination.next_button:
            print("\nTest 7: Checking pagination...")
            try:
                next_button = await self.page.query_selector(
                    config.pagination.next_button
                )
                if next_button:
                    results["tests"]["pagination"] = {"success": True}
                    print(
                        f"  ✓ Found pagination button: {config.pagination.next_button}"
                    )
                else:
                    results["tests"]["pagination"] = {
                        "success": False,
                        "error": "Pagination button not found",
                    }
                    print("  ⚠ Pagination button not found (might be on later pages)")
            except Exception as e:
                results["tests"]["pagination"] = {"success": False, "error": str(e)}
                print(f"  ⚠ Error checking pagination: {e}")

        # Test 8: Navigate to first result and test detail selectors
        if result_elements and len(result_elements) > 0:
            print("\nTest 8: Testing detail page selectors...")
            try:
                first_link = result_elements[0]
                detail_url = await first_link.get_attribute("href")

                # Make URL absolute
                if detail_url and not detail_url.startswith("http"):
                    detail_url = f"{config.base_url}{detail_url}"

                print(f"  Navigating to: {detail_url}")
                await self.page.goto(detail_url)
                await self.page.wait_for_load_state("networkidle")

                detail_tests = {}

                # Test detail title
                if config.selectors.detail_title:
                    title_el = await self.page.query_selector(
                        config.selectors.detail_title
                    )
                    if title_el:
                        title_text = await title_el.inner_text()
                        detail_tests["title"] = {
                            "success": True,
                            "preview": title_text[:50],
                        }
                        print(f"  ✓ Found detail title: {title_text[:50]}...")
                    else:
                        detail_tests["title"] = {"success": False}
                        print("  ⚠ Detail title not found")

                # Test detail content
                if config.selectors.detail_content:
                    content_el = await self.page.query_selector(
                        config.selectors.detail_content
                    )
                    if content_el:
                        content_text = await content_el.inner_text()
                        detail_tests["content"] = {
                            "success": True,
                            "length": len(content_text),
                            "preview": content_text[:100],
                        }
                        print(f"  ✓ Found detail content ({len(content_text)} chars)")
                    else:
                        detail_tests["content"] = {"success": False}
                        print("  ⚠ Detail content not found")

                # Test detail date
                if config.selectors.detail_date:
                    date_el = await self.page.query_selector(
                        config.selectors.detail_date
                    )
                    if date_el:
                        date_text = await date_el.inner_text()
                        detail_tests["date"] = {"success": True, "value": date_text}
                        print(f"  ✓ Found detail date: {date_text}")
                    else:
                        detail_tests["date"] = {"success": False}
                        print("  ⚠ Detail date not found")

                # Test detail author
                if config.selectors.detail_author:
                    author_el = await self.page.query_selector(
                        config.selectors.detail_author
                    )
                    if author_el:
                        author_text = await author_el.inner_text()
                        detail_tests["author"] = {"success": True, "value": author_text}
                        print(f"  ✓ Found detail author: {author_text}")
                    else:
                        detail_tests["author"] = {"success": False}
                        print("  ⚠ Detail author not found")

                results["tests"]["detail_page"] = {
                    "success": True,
                    "detail_tests": detail_tests,
                }

            except Exception as e:
                results["tests"]["detail_page"] = {"success": False, "error": str(e)}
                print(f"  ⚠ Error testing detail page: {e}")

        # Summary
        print(f"\n{'='*60}")
        total_tests = len(results["tests"])
        passed_tests = sum(
            1 for t in results["tests"].values() if t.get("success", False)
        )
        print(f"Test Summary: {passed_tests}/{total_tests} tests passed")

        if results["success"]:
            print("✓ Configuration is valid and ready to use!")
        else:
            print("✗ Configuration has issues that need to be fixed")
        print(f"{'='*60}\n")

        return results


async def test_all_configs(headless: bool = False):
    """
    Test all available configurations.

    Args:
        headless: Run browser in headless mode
    """
    manager = get_config_manager()
    sites = manager.list_sites()

    print(f"\nTesting {len(sites)} site configurations...")

    results = {}
    async with ConfigTester(headless=headless) as tester:
        for site_name in sites:
            try:
                result = await tester.test_configuration(site_name)
                results[site_name] = result

                # Small delay between sites
                await asyncio.sleep(2)
            except Exception as e:
                results[site_name] = {"success": False, "error": str(e)}
                print(f"\nFailed to test {site_name}: {e}\n")

    # Overall summary
    print(f"\n{'='*60}")
    print("Overall Summary")
    print(f"{'='*60}")

    for site_name, result in results.items():
        status = "✓" if result.get("success") else "✗"
        print(f"{status} {site_name}")

    passed = sum(1 for r in results.values() if r.get("success"))
    print(f"\n{passed}/{len(sites)} configurations passed")


async def main():
    """Main function for command-line usage."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python test_config.py <site_name> [test_query]")
        print("   or: python test_config.py --all")
        print("\nAvailable sites:")
        manager = get_config_manager()
        for site in manager.list_sites():
            print(f"  - {site}")
        return

    if sys.argv[1] == "--all":
        await test_all_configs(headless=False)
    else:
        site_name = sys.argv[1]
        test_query = sys.argv[2] if len(sys.argv) > 2 else "test"

        async with ConfigTester(headless=False) as tester:
            await tester.test_configuration(site_name, test_query)


if __name__ == "__main__":
    asyncio.run(main())
