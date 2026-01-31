"""
Interactive configuration builder for creating site configs.

This utility helps create YAML configuration files for new sites
through an interactive CLI or programmatic interface.
"""

from pathlib import Path
from typing import Optional
from webScraper.config.site_config import (
    SiteConfig,
    SelectorConfig,
    RateLimitConfig,
    PaginationConfig,
    AuthenticationConfig,
)


class ConfigBuilder:
    """Interactive builder for site configurations."""

    def __init__(self):
        """Initialize the config builder."""
        self.config_data = {}

    def interactive_build(self) -> SiteConfig:
        """
        Build configuration interactively through CLI prompts.

        Returns:
            SiteConfig instance
        """
        print("\n" + "=" * 60)
        print("Site Configuration Builder")
        print("=" * 60 + "\n")

        # Basic site info
        print("Basic Site Information")
        print("-" * 40)
        site_name = input("Site name (e.g., 'doj_gov'): ").strip()
        base_url = input("Base URL (e.g., 'https://example.com'): ").strip()
        search_url = input("Search URL: ").strip()

        # Selectors
        print("\n" + "=" * 60)
        print("CSS Selectors")
        print("=" * 60)
        print("\nSearch Page Selectors:")
        search_input = input("Search input selector: ").strip()
        search_button = input("Search button selector: ").strip()
        result_links = input("Result links selector: ").strip()
        result_title = self._optional_input("Result title selector (optional): ")
        result_snippet = self._optional_input("Result snippet selector (optional): ")

        print("\nDetail Page Selectors:")
        detail_title = self._optional_input("Detail title selector (optional): ")
        detail_content = self._optional_input("Detail content selector (optional): ")
        detail_date = self._optional_input("Detail date selector (optional): ")
        detail_author = self._optional_input("Detail author selector (optional): ")
        detail_tags = self._optional_input("Detail tags selector (optional): ")

        # Custom selectors
        custom_selectors = {}
        print("\nCustom Selectors (press Enter without input to skip):")
        while True:
            key = input("Custom field name: ").strip()
            if not key:
                break
            selector = input(f"Selector for '{key}': ").strip()
            if selector:
                custom_selectors[key] = selector

        selectors = SelectorConfig(
            search_input=search_input,
            search_button=search_button,
            result_links=result_links,
            result_title=result_title,
            result_snippet=result_snippet,
            next_page=None,  # Set later in pagination
            detail_title=detail_title,
            detail_content=detail_content,
            detail_date=detail_date,
            detail_author=detail_author,
            detail_tags=detail_tags,
            custom=custom_selectors,
        )

        # Rate limiting
        print("\n" + "=" * 60)
        print("Rate Limiting")
        print("=" * 60)
        rpm = int(input("Requests per minute [20]: ") or "20")
        delay_min = float(
            input("Minimum delay between requests (seconds) [1]: ") or "1"
        )
        delay_max = float(
            input("Maximum delay between requests (seconds) [3]: ") or "3"
        )

        rate_limit = RateLimitConfig(
            requests_per_minute=rpm,
            delay_range=(delay_min, delay_max),
            max_concurrent=1,
            respect_robots_txt=True,
        )

        # Pagination
        print("\n" + "=" * 60)
        print("Pagination")
        print("=" * 60)
        has_pagination = (
            input("Does the site have pagination? (y/n) [n]: ").lower() == "y"
        )

        if has_pagination:
            next_button = input("Next page button selector: ").strip()
            max_pages = self._optional_input("Maximum pages to scrape (optional): ")
            if max_pages:
                max_pages = int(max_pages)

            pagination = PaginationConfig(
                enabled=True,
                next_button=next_button,
                max_pages=max_pages,
                pagination_type="button",
            )
            selectors.next_page = next_button
        else:
            pagination = PaginationConfig(enabled=False)

        # Authentication
        print("\n" + "=" * 60)
        print("Authentication")
        print("=" * 60)
        needs_auth = (
            input("Does the site require authentication? (y/n) [n]: ").lower() == "y"
        )

        if needs_auth:
            print("Authentication types: none, basic, form, oauth")
            auth_type = input("Authentication type [form]: ").strip() or "form"
            login_url = input("Login URL: ").strip()
            username_field = input("Username field selector: ").strip()
            password_field = input("Password field selector: ").strip()
            submit_button = input("Submit button selector: ").strip()
            creds_env = input(
                "Environment variable for credentials (USERNAME:PASSWORD): "
            ).strip()

            authentication = AuthenticationConfig(
                required=True,
                auth_type=auth_type,
                login_url=login_url,
                username_field=username_field,
                password_field=password_field,
                submit_button=submit_button,
                credentials_env_var=creds_env,
            )
        else:
            authentication = AuthenticationConfig(required=False)

        # Additional settings
        print("\n" + "=" * 60)
        print("Additional Settings")
        print("=" * 60)
        js_required = (
            input("Does the site require JavaScript? (y/n) [y]: ").lower() != "n"
        )
        wait_selector = self._optional_input("Wait for selector (optional): ")
        timeout = int(input("Wait timeout (ms) [10000]: ") or "10000")

        # Metadata
        print("\nSite Metadata (optional):")
        description = self._optional_input("Site description: ")
        category = self._optional_input("Category: ")
        content_type = self._optional_input("Primary content type: ")

        metadata = {}
        if description:
            metadata["description"] = description
        if category:
            metadata["category"] = category
        if content_type:
            metadata["primary_content_type"] = content_type

        # Create config
        config = SiteConfig(
            site_name=site_name,
            base_url=base_url,
            search_url=search_url,
            selectors=selectors,
            rate_limit=rate_limit,
            pagination=pagination,
            authentication=authentication,
            javascript_required=js_required,
            wait_for_selector=wait_selector,
            wait_for_timeout=timeout,
            metadata=metadata,
        )

        return config

    def _optional_input(self, prompt: str) -> Optional[str]:
        """Get optional input from user."""
        value = input(prompt).strip()
        return value if value else None

    def quick_build(
        self,
        site_name: str,
        base_url: str,
        search_url: str,
        search_input: str,
        search_button: str,
        result_links: str,
        **kwargs,
    ) -> SiteConfig:
        """
        Quickly build a basic configuration programmatically.

        Args:
            site_name: Name of the site
            base_url: Base URL
            search_url: Search URL
            search_input: Search input selector
            search_button: Search button selector
            result_links: Result links selector
            **kwargs: Additional optional parameters

        Returns:
            SiteConfig instance
        """
        selectors = SelectorConfig(
            search_input=search_input,
            search_button=search_button,
            result_links=result_links,
            result_title=kwargs.get("result_title"),
            result_snippet=kwargs.get("result_snippet"),
            next_page=kwargs.get("next_page"),
            detail_title=kwargs.get("detail_title"),
            detail_content=kwargs.get("detail_content"),
            detail_date=kwargs.get("detail_date"),
            detail_author=kwargs.get("detail_author"),
            detail_tags=kwargs.get("detail_tags"),
            custom=kwargs.get("custom_selectors", {}),
        )

        rate_limit = RateLimitConfig(
            requests_per_minute=kwargs.get("requests_per_minute", 20),
            delay_range=kwargs.get("delay_range", (1, 3)),
            max_concurrent=kwargs.get("max_concurrent", 1),
            respect_robots_txt=kwargs.get("respect_robots_txt", True),
        )

        pagination = PaginationConfig(
            enabled=kwargs.get("pagination_enabled", False),
            next_button=kwargs.get("next_button"),
            max_pages=kwargs.get("max_pages"),
            pagination_type=kwargs.get("pagination_type", "button"),
        )

        authentication = AuthenticationConfig(
            required=kwargs.get("auth_required", False)
        )

        return SiteConfig(
            site_name=site_name,
            base_url=base_url,
            search_url=search_url,
            selectors=selectors,
            rate_limit=rate_limit,
            pagination=pagination,
            authentication=authentication,
            javascript_required=kwargs.get("javascript_required", True),
            wait_for_selector=kwargs.get("wait_for_selector"),
            wait_for_timeout=kwargs.get("wait_for_timeout", 10000),
            headers=kwargs.get("headers", {}),
            metadata=kwargs.get("metadata", {}),
        )

    def save_config(
        self, config: SiteConfig, output_dir: Optional[Path] = None
    ) -> Path:
        """
        Save configuration to YAML file.

        Args:
            config: SiteConfig to save
            output_dir: Directory to save to (defaults to config/sites)

        Returns:
            Path to saved file
        """
        if output_dir is None:
            output_dir = Path("./webScraper/config/sites")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{config.site_name}.yaml"

        config.to_yaml(output_path)
        print(f"\n✓ Configuration saved to: {output_path}")

        return output_path


def main():
    """Main function for interactive config creation."""
    builder = ConfigBuilder()

    print("\nChoose build mode:")
    print("1. Interactive mode (step-by-step)")
    print("2. Quick mode (minimal configuration)")

    choice = input("\nEnter choice [1]: ").strip() or "1"

    if choice == "1":
        config = builder.interactive_build()
    else:
        print("\nQuick configuration mode")
        site_name = input("Site name: ").strip()
        base_url = input("Base URL: ").strip()
        search_url = input("Search URL: ").strip()
        search_input = input("Search input selector: ").strip()
        search_button = input("Search button selector: ").strip()
        result_links = input("Result links selector: ").strip()

        config = builder.quick_build(
            site_name=site_name,
            base_url=base_url,
            search_url=search_url,
            search_input=search_input,
            search_button=search_button,
            result_links=result_links,
        )

    # Preview configuration
    print("\n" + "=" * 60)
    print("Configuration Preview")
    print("=" * 60)
    print(f"Site: {config.site_name}")
    print(f"Base URL: {config.base_url}")
    print(f"Search URL: {config.search_url}")
    print(f"Rate Limit: {config.rate_limit.requests_per_minute} req/min")
    print(f"Pagination: {'Enabled' if config.pagination.enabled else 'Disabled'}")
    print(
        f"Authentication: {'Required' if config.authentication.required else 'Not required'}"
    )

    # Save
    save = input("\nSave this configuration? (y/n) [y]: ").lower() != "n"
    if save:
        builder.save_config(config)
        print("\n✓ Configuration ready! You can now use:")
        print(f"   GenericScraper(site_name='{config.site_name}')")
    else:
        print("\nConfiguration not saved.")


if __name__ == "__main__":
    main()
