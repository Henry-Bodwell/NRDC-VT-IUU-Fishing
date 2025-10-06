"""
Global settings and configuration for the web scraper.

This module provides default settings and configuration management
for the entire scraping system.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from pathlib import Path
import os


@dataclass
class BrowserSettings:
    """Browser-related configuration."""

    headless: bool = True
    timeout: int = 30000  # milliseconds
    user_agent: Optional[str] = None
    viewport: Dict[str, int] = field(
        default_factory=lambda: {"width": 1280, "height": 720}
    )
    # Browser type: 'chromium', 'firefox', or 'webkit'
    browser_type: str = "chromium"
    # Additional launch options
    launch_options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScrapingSettings:
    """Scraping behavior configuration."""

    max_retries: int = 3
    delay_range: tuple = (1, 5)  # seconds between requests
    max_concurrent_pages: int = 3  # for parallel scraping
    respect_robots_txt: bool = True
    default_max_results: int = 100
    # Enable JavaScript execution
    javascript_enabled: bool = True
    # Take screenshots on error
    screenshot_on_error: bool = True


@dataclass
class StorageSettings:
    """Storage and output configuration."""

    # Base directory for all output
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    # Default storage format: 'json', 'csv', 'db'
    default_format: str = "json"
    # Create timestamped subdirectories
    use_timestamps: bool = True
    # Save screenshots
    save_screenshots: bool = False
    screenshot_dir: Path = field(default_factory=lambda: Path("./output/screenshots"))


@dataclass
class LoggingSettings:
    """Logging configuration."""

    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    log_dir: Path = field(default_factory=lambda: Path("./logs"))
    log_to_file: bool = True
    log_to_console: bool = True
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    # Rotate logs
    max_log_size_mb: int = 10
    backup_count: int = 5


@dataclass
class GlobalSettings:
    """Global configuration container."""

    browser: BrowserSettings = field(default_factory=BrowserSettings)
    scraping: ScrapingSettings = field(default_factory=ScrapingSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)

    # Site configurations directory
    sites_config_dir: Path = field(
        default_factory=lambda: Path("./webScraper/config/sites")
    )

    def __post_init__(self):
        """Ensure directories exist."""
        self.storage.output_dir.mkdir(parents=True, exist_ok=True)
        self.storage.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.logging.log_dir.mkdir(parents=True, exist_ok=True)
        self.sites_config_dir.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = GlobalSettings()


def get_settings() -> GlobalSettings:
    """
    Get the global settings instance.

    Returns:
        GlobalSettings instance
    """
    return settings


def update_settings(**kwargs) -> None:
    """
    Update global settings.

    Args:
        **kwargs: Settings to update (nested with dots, e.g., browser.headless=False)
    """
    global settings

    for key, value in kwargs.items():
        parts = key.split(".")
        obj = settings

        # Navigate to nested attribute
        for part in parts[:-1]:
            obj = getattr(obj, part)

        # Set the value
        setattr(obj, parts[-1], value)


def load_env_settings() -> None:
    """
    Load settings from environment variables.

    Environment variables should be prefixed with SCRAPER_ and use underscores.
    Example: SCRAPER_BROWSER_HEADLESS=false
    """
    prefix = "SCRAPER_"

    for key, value in os.environ.items():
        if key.startswith(prefix):
            # Remove prefix and convert to lowercase
            setting_key = key[len(prefix) :].lower().replace("_", ".")

            # Convert string values to appropriate types
            if value.lower() in ("true", "false"):
                value = value.lower() == "true"
            elif value.isdigit():
                value = int(value)
            elif value.replace(".", "").isdigit():
                value = float(value)

            try:
                update_settings(**{setting_key: value})
            except AttributeError:
                pass  # Invalid setting key


# Load environment settings on module import
load_env_settings()
