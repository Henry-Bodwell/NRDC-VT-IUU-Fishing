# webScraper Module

A flexible, configuration-driven web scraping framework built with Playwright and Python.

## Import Issues - FIXED ✓

All import issues have been resolved! The module now uses proper absolute imports with the `webScraper` package prefix.

### What Was Fixed

1. **`__init__.py` files** - Updated to use `webScraper.` prefix
2. **Module imports** - Changed from relative (`from config.`) to absolute (`from webScraper.config.`)
3. **Configuration path** - Updated default config directory from `./config/sites` to `./webScraper/config/sites`

### Testing Imports

Run the test script to verify all imports:

```bash
python -m webScraper.test_imports
```

## Quick Start

```python
from webScraper import scrape_site
import asyncio

# Scrape a configured site
results = asyncio.run(scrape_site('doj_gov', 'illegal fishing', max_results=10))

for result in results:
    print(f"Title: {result.title}")
    print(f"URL: {result.url}")
    print(f"Content: {result.content[:200]}...")
```

## Architecture

### Core Components

- **[base_scraper.py](scrapers/base_scraper.py)** - Abstract base class with template method pattern
- **[generic_scraper.py](scrapers/generic_scraper.py)** - YAML-driven scraper (no custom code needed!)
- **[site_config.py](config/site_config.py)** - Configuration system for sites
- **[settings.py](config/settings.py)** - Global browser and scraping settings
- **[config_builder.py](utils/config_builder.py)** - Interactive CLI for creating configs
- **[test_config.py](utils/test_config.py)** - Test and validate site configurations

### Configuration Files

Site configs are stored in `webScraper/config/sites/` as YAML files.

Example: [doj_gov.yaml](config/sites/doj_gov.yaml)

## Usage Examples

### Using GenericScraper

```python
from webScraper import GenericScraper
import asyncio

async def main():
    scraper = GenericScraper(site_name='doj_gov', headless=True)
    results = await scraper.scrape(
        query='illegal fishing',
        max_results=20,
        scrape_details=True
    )
    return results

asyncio.run(main())
```

### Creating a Custom Scraper

```python
from webScraper.scrapers import BaseScraper, SearchResult, ScrapedContent

class MyCustomScraper(BaseScraper):
    async def navigate_to_search(self):
        await self.page.goto("https://example.com/search")

    async def submit_query(self, query: str):
        await self.page.fill("#search-input", query)
        await self.page.click("#search-button")

    async def extract_result_links(self):
        # Extract links from search results
        pass

    async def scrape_detail_page(self, result: SearchResult):
        # Extract content from detail pages
        pass
```

### Creating a New Site Config

#### Interactive Mode

```bash
python -m webScraper.utils.config_builder
```

#### Programmatic

```python
from webScraper.utils import ConfigBuilder

builder = ConfigBuilder()
config = builder.quick_build(
    site_name="example_site",
    base_url="https://example.com",
    search_url="https://example.com/search",
    search_input='input[name="q"]',
    search_button='button[type="submit"]',
    result_links='a.result-link',
    detail_title='h1.title',
    detail_content='div.content',
)
builder.save_config(config)
```

### Testing a Configuration

```bash
# Test a specific site
python -m webScraper.utils.test_config doj_gov "illegal fishing"

# Test all configured sites
python -m webScraper.utils.test_config --all
```

## Features

✅ **Template Method Pattern** - Consistent workflow with site-specific customization
✅ **YAML-driven configs** - No code needed for most sites
✅ **Retry logic** - Automatic retry with exponential backoff
✅ **Rate limiting** - Random delays to appear human-like
✅ **Pagination support** - Button-based and URL-based
✅ **Authentication** - Form-based and basic auth support
✅ **Custom headers & cookies** - Full control over requests
✅ **Interactive config builder** - CLI for easy setup
✅ **Config testing tool** - Validate selectors before scraping

## Configuration Options

See [site_config.py](config/site_config.py) for full details. Key sections:

- **Selectors** - CSS selectors for search and detail pages
- **Rate Limiting** - Requests per minute, delay ranges
- **Pagination** - Button or URL-based navigation
- **Authentication** - Login credentials and flow
- **Browser Settings** - Headless mode, timeout, user agent

## Development

### Project Structure

```
webScraper/
├── __init__.py              # Package exports
├── config/
│   ├── __init__.py
│   ├── settings.py          # Global settings
│   ├── site_config.py       # Site configurations
│   └── sites/
│       └── doj_gov.yaml     # Example site config
├── scrapers/
│   ├── __init__.py
│   ├── base_scraper.py      # Abstract base class
│   ├── generic_scraper.py   # YAML-driven scraper
│   └── sites/
│       └── example.py       # Example custom scraper
└── utils/
    ├── __init__.py
    ├── config_builder.py    # Config creation tool
    └── test_config.py       # Config testing tool
```

### Adding a New Site

1. **Option A - Use existing config**:
   ```bash
   python -m webScraper.utils.config_builder
   ```

2. **Option B - Copy and modify**:
   - Copy `config/sites/doj_gov.yaml`
   - Update selectors for your site
   - Test with `test_config.py`

3. **Option C - Custom scraper**:
   - Extend `BaseScraper`
   - Implement abstract methods
   - See `scrapers/sites/example.py`

## Next Steps

- [ ] Add more site configurations (NOAA, Interpol, etc.)
- [ ] Integrate with main IUU-Fishing pipeline
- [ ] Add data export (JSON/CSV/MongoDB)
- [ ] Create CLI for running scrapers
- [ ] Add proxy support
- [ ] Implement JavaScript-heavy site support

## License

MIT
