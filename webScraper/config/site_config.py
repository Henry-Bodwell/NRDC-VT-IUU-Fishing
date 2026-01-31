"""
Site-specific configuration manager.

This module handles loading and managing site-specific configurations
from YAML files.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from pathlib import Path
import yaml
from webScraper.config.settings import get_settings


@dataclass
class SelectorConfig:
    """CSS/XPath selectors for a site."""

    search_input: str
    search_button: str
    result_links: str
    result_title: Optional[str] = None
    result_snippet: Optional[str] = None
    next_page: Optional[str] = None
    detail_title: Optional[str] = None
    detail_content: Optional[str] = None
    detail_date: Optional[str] = None
    detail_author: Optional[str] = None
    detail_tags: Optional[str] = None
    # Additional custom selectors
    custom: Dict[str, str] = field(default_factory=dict)


@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""

    requests_per_minute: int = 20
    delay_range: tuple = (1, 3)  # seconds
    max_concurrent: int = 1
    respect_robots_txt: bool = True


@dataclass
class PaginationConfig:
    """Pagination handling configuration."""

    enabled: bool = False
    next_button: Optional[str] = None
    max_pages: Optional[int] = None
    # 'button', 'url_pattern', or 'infinite_scroll'
    pagination_type: str = "button"
    url_pattern: Optional[str] = None  # e.g., "?page={page}"


@dataclass
class AuthenticationConfig:
    """Authentication configuration."""

    required: bool = False
    auth_type: str = "none"  # 'none', 'basic', 'form', 'oauth'
    login_url: Optional[str] = None
    username_field: Optional[str] = None
    password_field: Optional[str] = None
    submit_button: Optional[str] = None
    # Credentials should be loaded from environment or secure storage
    credentials_env_var: Optional[str] = None
    # Logout configuration
    logout_url: Optional[str] = None
    logout_button: Optional[str] = None
    logout_hover_target: Optional[str] = (
        None  # Element to hover over before clicking logout_button
    )


@dataclass
class SiteConfig:
    """Complete configuration for a specific site."""

    site_name: str
    base_url: str
    search_url: str
    selectors: SelectorConfig
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    pagination: PaginationConfig = field(default_factory=PaginationConfig)
    authentication: AuthenticationConfig = field(default_factory=AuthenticationConfig)

    # Additional site-specific settings
    javascript_required: bool = True
    wait_for_selector: Optional[str] = None
    wait_for_timeout: int = 10000

    # Custom headers
    headers: Dict[str, str] = field(default_factory=dict)

    # Cookies to set
    cookies: List[Dict[str, Any]] = field(default_factory=list)

    # Site-specific metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "SiteConfig":
        """
        Load site configuration from YAML file.

        Args:
            yaml_path: Path to YAML configuration file

        Returns:
            SiteConfig instance
        """
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)

        # Parse selectors
        selectors_data = data.get("selectors", {})
        selectors = SelectorConfig(
            search_input=selectors_data.get("search_input", ""),
            search_button=selectors_data.get("search_button", ""),
            result_links=selectors_data.get("result_links", ""),
            result_title=selectors_data.get("result_title"),
            result_snippet=selectors_data.get("result_snippet"),
            next_page=selectors_data.get("next_page"),
            detail_title=selectors_data.get("detail_title"),
            detail_content=selectors_data.get("detail_content"),
            detail_date=selectors_data.get("detail_date"),
            detail_author=selectors_data.get("detail_author"),
            detail_tags=selectors_data.get("detail_tags"),
            custom=selectors_data.get("custom", {}),
        )

        # Parse rate limit
        rate_limit_data = data.get("rate_limit", {})
        rate_limit = RateLimitConfig(
            requests_per_minute=rate_limit_data.get("requests_per_minute", 20),
            delay_range=tuple(rate_limit_data.get("delay_range", [1, 3])),
            max_concurrent=rate_limit_data.get("max_concurrent", 1),
            respect_robots_txt=rate_limit_data.get("respect_robots_txt", True),
        )

        # Parse pagination
        pagination_data = data.get("pagination", {})
        pagination = PaginationConfig(
            enabled=pagination_data.get("enabled", False),
            next_button=pagination_data.get("next_button"),
            max_pages=pagination_data.get("max_pages"),
            pagination_type=pagination_data.get("pagination_type", "button"),
            url_pattern=pagination_data.get("url_pattern"),
        )

        # Parse authentication
        auth_data = data.get("authentication", {})
        authentication = AuthenticationConfig(
            required=auth_data.get("required", False),
            auth_type=auth_data.get("auth_type", "none"),
            login_url=auth_data.get("login_url"),
            username_field=auth_data.get("username_field"),
            password_field=auth_data.get("password_field"),
            submit_button=auth_data.get("submit_button"),
            credentials_env_var=auth_data.get("credentials_env_var"),
            logout_url=auth_data.get("logout_url"),
            logout_button=auth_data.get("logout_button"),
            logout_hover_target=auth_data.get("logout_hover_target"),
        )

        return cls(
            site_name=data.get("site_name", ""),
            base_url=data.get("base_url", ""),
            search_url=data.get("search_url", ""),
            selectors=selectors,
            rate_limit=rate_limit,
            pagination=pagination,
            authentication=authentication,
            javascript_required=data.get("javascript_required", True),
            wait_for_selector=data.get("wait_for_selector"),
            wait_for_timeout=data.get("wait_for_timeout", 10000),
            headers=data.get("headers", {}),
            cookies=data.get("cookies", []),
            metadata=data.get("metadata", {}),
        )

    def to_yaml(self, yaml_path: Path) -> None:
        """
        Save configuration to YAML file.

        Args:
            yaml_path: Path where to save the YAML file
        """
        data = {
            "site_name": self.site_name,
            "base_url": self.base_url,
            "search_url": self.search_url,
            "selectors": {
                "search_input": self.selectors.search_input,
                "search_button": self.selectors.search_button,
                "result_links": self.selectors.result_links,
                "result_title": self.selectors.result_title,
                "result_snippet": self.selectors.result_snippet,
                "next_page": self.selectors.next_page,
                "detail_title": self.selectors.detail_title,
                "detail_content": self.selectors.detail_content,
                "detail_date": self.selectors.detail_date,
                "detail_author": self.selectors.detail_author,
                "detail_tags": self.selectors.detail_tags,
                "custom": self.selectors.custom,
            },
            "rate_limit": {
                "requests_per_minute": self.rate_limit.requests_per_minute,
                "delay_range": list(self.rate_limit.delay_range),
                "max_concurrent": self.rate_limit.max_concurrent,
                "respect_robots_txt": self.rate_limit.respect_robots_txt,
            },
            "pagination": {
                "enabled": self.pagination.enabled,
                "next_button": self.pagination.next_button,
                "max_pages": self.pagination.max_pages,
                "pagination_type": self.pagination.pagination_type,
                "url_pattern": self.pagination.url_pattern,
            },
            "authentication": {
                "required": self.authentication.required,
                "auth_type": self.authentication.auth_type,
                "login_url": self.authentication.login_url,
                "username_field": self.authentication.username_field,
                "password_field": self.authentication.password_field,
                "submit_button": self.authentication.submit_button,
                "credentials_env_var": self.authentication.credentials_env_var,
            },
            "javascript_required": self.javascript_required,
            "wait_for_selector": self.wait_for_selector,
            "wait_for_timeout": self.wait_for_timeout,
            "headers": self.headers,
            "cookies": self.cookies,
            "metadata": self.metadata,
        }

        with open(yaml_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)


class ConfigManager:
    """Manager for loading and accessing site configurations."""

    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize the configuration manager.

        Args:
            config_dir: Directory containing site configuration files
        """
        if config_dir is None:
            config_dir = get_settings().sites_config_dir

        self.config_dir = Path(config_dir)
        self.configs: Dict[str, SiteConfig] = {}
        self._load_all_configs()

    def _load_all_configs(self) -> None:
        """Load all YAML configurations from the config directory."""
        if not self.config_dir.exists():
            return

        for yaml_file in self.config_dir.glob("*.yaml"):
            try:
                config = SiteConfig.from_yaml(yaml_file)
                self.configs[config.site_name] = config
            except Exception as e:
                print(f"Warning: Failed to load config from {yaml_file}: {e}")

    def get_config(self, site_name: str) -> Optional[SiteConfig]:
        """
        Get configuration for a specific site.

        Args:
            site_name: Name of the site

        Returns:
            SiteConfig if found, None otherwise
        """
        return self.configs.get(site_name)

    def list_sites(self) -> List[str]:
        """
        Get list of all configured sites.

        Returns:
            List of site names
        """
        return list(self.configs.keys())

    def add_config(self, config: SiteConfig, save: bool = True) -> None:
        """
        Add or update a site configuration.

        Args:
            config: SiteConfig instance to add
            save: Whether to save to YAML file
        """
        self.configs[config.site_name] = config

        if save:
            yaml_path = self.config_dir / f"{config.site_name}.yaml"
            config.to_yaml(yaml_path)

    def remove_config(self, site_name: str, delete_file: bool = False) -> None:
        """
        Remove a site configuration.

        Args:
            site_name: Name of the site to remove
            delete_file: Whether to delete the YAML file
        """
        if site_name in self.configs:
            del self.configs[site_name]

        if delete_file:
            yaml_path = self.config_dir / f"{site_name}.yaml"
            if yaml_path.exists():
                yaml_path.unlink()

    def reload_configs(self) -> None:
        """Reload all configurations from disk."""
        self.configs.clear()
        self._load_all_configs()


# Global config manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """
    Get the global configuration manager instance.

    Returns:
        ConfigManager instance
    """
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_site_config(site_name: str) -> Optional[SiteConfig]:
    """
    Convenience function to get a site configuration.

    Args:
        site_name: Name of the site

    Returns:
        SiteConfig if found, None otherwise
    """
    return get_config_manager().get_config(site_name)
