import dspy
from bs4 import BeautifulSoup
import requests
import json
from dotenv import load_dotenv
import os
from webscraping.schemas import IncidentAnalysisModule


class NewsAnalysisTool:
    def __init__(self, model = 'openai/gpt-4o-mini', api_key: str = None):
        """Initialize the NewsScraper with gpt 4o mini."""
        self.lm = dspy.LM(model, api_key=api_key)
        dspy.settings.configure(lm=self.lm)

        self.analysisTool = IncidentAnalysisModule()
        self.articleClassificationTool = dspy.ChainOfThought(
            dspy.ArticleClassificationSignature)
        self.optimized_analysisTool = None

    def fetch_article_from_url(self, url: str) -> str:
        """Fetch article content from a given URL."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()  # Raise an exception for bad status codes
            
            # Parse HTML and extract text
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script, style, header, footer, and nav elements for cleaner text
            for element in soup(["script", "style", "header", "footer", "nav", "aside"]):
                element.decompose()
            
            # Attempt to find the main content body (common tags)
            main_content = soup.find('article') or soup.find('main') or soup.body
            if not main_content:
                main_content = soup
                
            # Get text and clean it up
            text = main_content.get_text(separator=' ')
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)
            
            # Limit text length to avoid excessive token usage
            return text[:15000]

        except requests.exceptions.RequestException as e:
            print(f"Error fetching article from {url}: {e}")
            return ""
        except Exception as e:
            print(f"An unexpected error occurred during fetching/parsing from {url}: {e}")
            return ""

    def extract_from_text(self, article_text: str) -> dspy.Prediction:
        """Extract structured information from the provided text."""
        try:
            if (self.articleClassificationTool(article_text=article_text).classification.articleType == "Unrelated to IUU Fishing" or
                self.articleClassificationTool(article_text=article_text).classification.articleType == "Industry Overview"):
                raise ValueError("The article is unrelated to incident of IUU fishing, skipping extraction.")
            prediction = self.analysisTool(article_text=article_text)

            return prediction
        except Exception as e:
            raise Exception(f"Error during extraction: {str(e)}")
        
    def extract_from_url(self, url: str) -> dspy.Prediction:
        """Extract structured information from a news article at the given URL."""
        article_text = self.fetch_article_from_url(url)
        return self.extract_from_text(article_text)
    
    def format_results(self, analysis_output: dict) -> dict:
        """
        Formats the complex output from IncidentAnalysisModule into a clean dictionary.
        This function's job is to DUMP data that has already been parsed.
        """
        # 1. Get the Pydantic object for extraction, which was already parsed.
        parsed_extraction_obj = analysis_output.get('parsed_data')
        if not parsed_extraction_obj:
            raise KeyError("The key 'parsed_data' was not found in the analysis output.")

        # 2. Get the classification prediction object.
        classification_prediction = analysis_output.get('classification')
        if not classification_prediction:
            raise KeyError("The key 'classification' was not found in the analysis output.")

        # 3. Get the Pydantic object for classification, which was also already parsed by DSPy.
        #    The 'classification' attribute on the prediction object IS the final object, not a string.
        parsed_classification_obj = classification_prediction.classification
        

        # 4. Now, simply DUMP both clean Pydantic objects into dictionaries.
        final_results = {
            "extracted_information": parsed_extraction_obj.model_dump(),
            "incident_classification": parsed_classification_obj.model_dump()
        }
        

        return final_results


def main():
    """Main function to run the NewsScraper."""
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    scraper = NewsAnalysisTool(model='openai/gpt-4o-mini', api_key=api_key)
    url = "https://cbcgdf.wordpress.com/2024/08/07/beijing-customs-intercepted-at-the-capital-airport-a-box-of-oahu-tree-snail-shells-cbcgdf-expert-shen-yihang-reports/"

    scraper.max_retries = 3  # Set the maximum number of retries for species verification
    results = scraper.extract_from_url(url)

    results_json = scraper.format_results(results)
    with open('news_analysis_results_verifier.json', 'w') as f:
        json.dump(results_json, f, indent=4)

    

if __name__ == "__main__":
    main()