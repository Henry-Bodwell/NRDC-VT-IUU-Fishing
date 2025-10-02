"""
Configuration package for web scraper.

This package provides global settings and site-specific configuration management.
"""

from webScraper.config.settings import (
    get_settings,
    update_settings,
    GlobalSettings,
    BrowserSettings,
    ScrapingSettings,
    StorageSettings,
    LoggingSettings,
)

from webScraper.config.site_config import (
    get_site_config,
    get_config_manager,
    SiteConfig,
    SelectorConfig,
    RateLimitConfig,
    PaginationConfig,
    AuthenticationConfig,
    ConfigManager,
)

__all__ = [
    # Settings
    "get_settings",
    "update_settings",
    "GlobalSettings",
    "BrowserSettings",
    "ScrapingSettings",
    "StorageSettings",
    "LoggingSettings",
    # Site Configuration
    "get_site_config",
    "get_config_manager",
    "SiteConfig",
    "SelectorConfig",
    "RateLimitConfig",
    "PaginationConfig",
    "AuthenticationConfig",
    "ConfigManager",
]
