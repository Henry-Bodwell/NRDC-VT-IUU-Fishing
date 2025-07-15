from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
import requests
from bs4 import BeautifulSoup
import time

@dataclass
class SelectorConfig:
    """Configuration for content selectors"""
    primary_selectors: List[Tuple[str, Dict[str, Any]]]  # (tag, attributes)
    fallback_selectors: List[Tuple[str, Dict[str, Any]]]
    text_selectors: Optional[List[Tuple[str, Dict[str, Any]]]] = None  # For specific text elements
    exclude_selectors: Optional[List[Tuple[str, Dict[str, Any]]]] = None  # Elements to remove
    
class BaseScraper(ABC):
    """Base scraper with common functionality"""
    
    def __init__(self, max_text_length: int = 15000, delay: float = 1.0):
        self.max_text_length = max_text_length
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def prep_article(self, url: str) -> Optional[BeautifulSoup]:
        """Prepare article soup from URL"""
        try:
            time.sleep(self.delay)
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            print(f"Successfully fetched article from {url}")
            soup = BeautifulSoup(response.content, 'html.parser')

            return soup
        except Exception as e:
            print(f"Error preparing article from {url}: {e}")
            return None
    
    def clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        cleaned = ' '.join(chunk for chunk in chunks if chunk)
        # print(cleaned[:1000])  # Print first 1000 characters for debugging
        return cleaned[:self.max_text_length]
    
    def extract_content_with_config(self, soup: BeautifulSoup, config: SelectorConfig) -> str:
        """Extract content using configuration"""
        if not soup:
            return ""
        
        # Remove unwanted elements first
        if config.exclude_selectors:
            for tag, attrs in config.exclude_selectors:
                for element in soup.find_all(tag, attrs):
                    element.decompose()
        
        # Try to find main content
        main_content = None
        
        # Try primary selectors first
        for tag, attrs in config.primary_selectors:
            main_content = soup.find(tag, attrs)
            if main_content:
                break
        
        # Fallback to other selectors
        if not main_content:
            for tag, attrs in config.fallback_selectors:
                main_content = soup.find(tag, attrs)
                if main_content:
                    break
        
        # Last resort - use body
        if not main_content:
            main_content = soup.body or soup
        
        # Extract text from specific elements if configured
        if config.text_selectors:
            text_parts = []
            for tag, attrs in config.text_selectors:
                elements = main_content.find_all(tag, attrs)
                for element in elements:
                    text = element.get_text(strip=True)
                    if text:
                        text_parts.append(text)
            text = '\n\n'.join(text_parts)
        else:
            # Default text extraction
            text = main_content.get_text(separator=' ')
          # Print first 1000 characters for debugging
        return self.clean_text(text)
    
    def scrape_article(self, url: str) -> str:
        """Main scraping method - to be implemented by subclasses"""
        try:
            soup = self.prep_article(url)
            if not soup:
                return ""
            
            config = self.get_selector_config()
            return self.extract_content_with_config(soup, config)
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching article from {url}: {e}")
            return ""
        except Exception as e:
            print(f"An unexpected error occurred during fetching/parsing from {url}: {e}")
            return ""
    
    @abstractmethod
    def get_selector_config(self) -> SelectorConfig:
        """Return the selector configuration for this scraper"""
        pass

class NewsScraper(BaseScraper):
    """Generic news scraper with common selectors"""
    
    def get_selector_config(self) -> SelectorConfig:
        return SelectorConfig(
            primary_selectors=[
                ('article', {}),
                ('main', {}),
                ('div', {'class': 'article-content'}),
                ('div', {'class': 'entry-content'}),
                ('div', {'id': 'content'}),
            ],
            fallback_selectors=[
                ('div', {'class': 'content'}),
                ('div', {'class': 'post-content'}),
                ('section', {'class': 'article-body'}),
                ('body', {}),
            ],
            exclude_selectors=[
                ('script', {}),
                ('style', {}),
                ('nav', {}),
                ('header', {}),
                ('footer', {}),
                ('aside', {}),
                ('div', {'class': 'advertisement'}),
                ('div', {'class': 'sidebar'}),
            ]
        )

class IntraFishScraper(BaseScraper):
    """Scraper for IntraFish articles - extracts only body content"""
    
    def get_selector_config(self) -> SelectorConfig:
        return SelectorConfig(
            primary_selectors=[
                ('div', {'id': 'dn-content'}),
            ],
            fallback_selectors=[
                ('div', {'class': 'dn-article-inline-content'}),
                ('div', {'class': 'dn-content'}),
                ('article', {}),
                ('main', {}),
                ('body', {}),
            ],
            text_selectors=[
                ('div', {'class': 'dn-text'}),    # Main content
                ('p', {'class': 'dn-text'}),      # More content
            ],
            exclude_selectors=[
                ('script', {}),
                ('style', {}),
                ('nav', {}),
                ('header', {}),
                ('footer', {}),
                ('figure', {}),
                ('figcaption', {}),
                ('div', {'class': 'topic-holder'}),
                ('h1', {'class': 'dn-headline'}),    # Remove title
                ('p', {'class': 'lead'}),           # Remove lead paragraph
                ('div', {'class': 'dn-meta-data'}), # Remove metadata
                ('div', {'class': 'dn-bylines-column'}), # Remove bylines
            ]
        )
    

class SeaFoodSourceScraper(BaseScraper):
    """Scraper for SeaFoodSource articles - extracts only body content"""
    
    def get_selector_config(self) -> SelectorConfig:
        return SelectorConfig(
            primary_selectors=[
                ('div', {'class': 'article__body'}),
                ('div', {'class': 'articleBodyWrap'}),
            ],
            fallback_selectors=[
                ('article', {}),
                ('main', {}),
                ('div', {'class': 'content'}),
                ('body', {}),
            ],
            text_selectors=[
                # Target the actual content containers
                ('div', {'class': 'article__body articleBodyWrap memberOnly t3p0-has-value'}),
                ('div', {'class': 'article__body articleBodyWrap t3p0-has-value'}),
                ('div', {'class': 'article__body'}),
                ('p', {}),  # Get any paragraphs within
            ],
            exclude_selectors=[
                ('script', {}),
                ('style', {}),
                ('nav', {}),
                ('header', {}),
                ('footer', {}),
                ('div', {'class': 't3p0-private-cta'}),          # Remove paywall CTA
                ('div', {'class': 'premium-member-cta'}),        # Remove premium CTA
                ('div', {'class': 't3p0-locked-content'}),       # Remove locked content indicators
                ('div', {'class': 't3p0-no-value'}),             # Remove empty content divs
                ('a', {'href': '/join'}),                        # Remove join links
                ('a', {'href': '/login'}),                       # Remove login links
                ('i', {'class': 'fa-solid fa-lock'}),            # Remove lock icons
                ('hr', {}),                                      # Remove horizontal rules
                ('img', {'alt': 'SeafoodSource Premium'}),       # Remove premium images
            ]
        )


class ScraperFactory:
    """Factory to create appropriate scrapers based on URL"""
    
    scrapers = {
        'intrafish.com': IntraFishScraper,
    }
    
    @classmethod
    def create_scraper(cls, url: str) -> BaseScraper:
        """Create appropriate scraper based on URL"""
        for domain, scraper_class in cls.scrapers.items():
            if domain in url:
                return scraper_class()
        
        # Default to generic news scraper
        return NewsScraper()
    
    @classmethod
    def register_scraper(cls, domain: str, scraper_class: type):
        """Register a new scraper for a domain"""
        cls.scrapers[domain] = scraper_class

# Usage example
if __name__ == "__main__":
    # Example usage
    # url = "https://www.intrafish.com/whitefish/norway-says-fisheries-cooperation-with-russia-will-continue-despite-sanctions/2-1-1843510"
    url = "https://www.seafoodsource.com/news/environment-sustainability/oceana-spanish-companies-are-top-offenders-of-hiding-vessel-ownership-information"
    scraper = SeaFoodSourceScraper()
    content = scraper.scrape_article(url)
    print(content[:1000])  # Print first 1000 characters of the content