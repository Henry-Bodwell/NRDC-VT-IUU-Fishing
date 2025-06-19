import csv
import dspy
from typing import Dict, List
from bs4 import BeautifulSoup
import requests
import json
from dotenv import load_dotenv
import os
from dspy.teleprompt import BootstrapFewShotWithRandomSearch

class NewsScraper:
    def __init__(self, model = 'openai/gpt-4o-mini', api_key: str = None):
        """Initialize the NewsScraper with gpt 4o mini."""
        self.lm = dspy.LM(model, api_key=api_key)
        dspy.settings.configure(lm=self.lm)

        self.scraper = dspy.ChainOfThought(ExtractIncidentData)
        self.optimized_scaper = None

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
            prediction = self.scraper(text=article_text)
            return prediction
        except Exception as e:
            raise Exception(f"Error during extraction: {str(e)}")
        
    def extract_from_url(self, url: str) -> dspy.Prediction:
        """Extract structured information from a news article at the given URL."""
        article_text = self.fetch_article_from_url(url)
        return self.extract_from_text(article_text)
    
    def format_results(self, prediction: dspy.Prediction) -> dict:
        """
        Format extraction results as a clean dictionary
        """
        return {
            "category": getattr(prediction, 'category', ''),
            "countryOfIncident": getattr(prediction, 'countryOfIncident', ''),
            "date": getattr(prediction, 'date', ''),
            "subject": getattr(prediction, 'subject', ''),
            "source": getattr(prediction, 'source', ''),
            "nameOfOrganizationProvidingInformation": getattr(prediction, 'nameOfOrganizationProvidingInformation', ''),
            "transportMode": getattr(prediction, 'transportMode', ''),
            "whereFound": getattr(prediction, 'whereFound', ''),
            "methodOfConcealment": getattr(prediction, 'methodOfConcealment', ''),
            "outcome": getattr(prediction, 'outcome', ''),
            "numberOfPeopleArrested": getattr(prediction, 'numberOfPeopleArrested', ''),
            "numberOfPeopleCharged": getattr(prediction, 'numberOfPeopleCharged', ''),
            "numberOfPeopleFined": getattr(prediction, 'numberOfPeopleFined', ''),
            "numberOfPeopleImprisioned": getattr(prediction, 'numberOfPeopleImprisioned', ''),
            "amountOfFines": getattr(prediction, 'amountOfFines', ''),
            "currencyOfFines": getattr(prediction, 'currencyOfFines', ''),
            "fineInUSD": getattr(prediction, 'fineInUSD', ''),
            "lengthOfImprisonment": getattr(prediction, 'lengthOfImprisonment', ''),
            "unitOfTime": getattr(prediction, 'unitOfTime', ''),
            "linksToCorruption": getattr(prediction, 'linksToCorruption', False),
            "description": getattr(prediction, 'description', ''),
            "reasoning": getattr(prediction, 'rationale', 'No reasoning provided')
        }
    
    def create_training_data(self, json_data: List[dict]) -> List[dspy.Example]:
        """
        Create training data from a list of JSON objects.
        Each object should contain the fields defined in ExtractIncidentData.
        """
        examples = []
        for item in json_data:
            source = item.get('Primary Source', '')
            article_text = self.fetch_article_from_url(source)
            if article_text:
                example = dspy.Example(
                    text=article_text,
                    category=item.get('Category of Incident', ''),
                    countryOfIncident=item.get('Country of Incident', ''),
                    date=item.get('Date of Incident', ''),
                    subject=item.get('Subject', ''),
                    source=source,
                    nameOfOrganizationProvidingInformation=item.get('Name of Organization Providing Information', ''),
                    transportMode=item.get('Transport Mode', ''),
                    whereFound=item.get('Where Found', ''),
                    methodOfConcealment=item.get('Method of Concealment', ''),
                    outcome=item.get('Outcome', ''),
                    numberOfPeopleArrested=item.get('Number of People Arrested', ''),
                    numberOfPeopleCharged=item.get('Number of People Charged', ''),
                    numberOfPeopleFined=item.get('Number of People Fined', ''),
                    numberOfPeopleImprisioned=item.get('Number of People Imprisioned', ''),
                    amountOfFines=item.get('Amount of Fine', ''),
                    currencyOfFines=item.get('Currency of Fine', ''),
                    fineInUSD=item.get('Fine in USD', ''),
                    lengthOfImprisonment=item.get('Length of Imprisonment', ''),
                    unitOfTime=item.get('Unit of Time', ''),
                    linksToCorruption=item.get('Links to Corruption', False)
                ).with_inputs('text')
            examples.append(example)
        return examples
    
    def evaluation_metric(self, example, pred, trace=None):
        """
        Custom evaluation metric for IUU incident extraction quality.
        Returns a score between 0 and 1, with higher weight on critical fields.
        """
        
        # Critical fields with higher weights
        critical_fields = [
            ('category', 2.0),
            ('countryOfIncident', 1.5),
            ('date', 1.5),
            ('subject', 1.5),
        ]
        
        # Important numerical fields
        numerical_fields = [
            ('numberOfPeopleArrested', 1.0),
            ('numberOfPeopleCharged', 1.0),
            ('numberOfPeopleFined', 1.0),
            ('numberOfPeopleImprisioned', 1.0),
            ('amountOfFines', 1.0),
            ('lengthOfImprisonment', 1.0)
        ]
        
        # Standard fields
        standard_fields = [
            ('source', 1.0),
            ('nameOfOrganizationProvidingInformation', 1.0),
            ('transportMode', 1.0),
            ('whereFound', 1.0),
            ('methodOfConcealment', 1.0),
            ('outcome', 1.0),
            ('currencyOfFines', 0.8),
            ('fineInUSD', 0.8),
            ('unitOfTime', 0.8)
        ]
        
        all_fields = critical_fields + numerical_fields + standard_fields
        
        total_weight = 0
        weighted_score = 0
        
        for field_name, weight in all_fields:
            expected = getattr(example, field_name, "").strip()
            predicted = getattr(pred, field_name, "").strip()
            
            total_weight += weight
            
            # Score the field
            if predicted:
                if expected:
                    # Calculate similarity score
                    if field_name in ['numberOfPeopleArrested', 'numberOfPeopleCharged', 
                                    'numberOfPeopleFined', 'numberOfPeopleImprisioned']:
                        # Exact match for numbers
                        field_score = 1.0 if predicted == expected else 0.0
                    elif field_name == 'linksToCorruption':
                        # Boolean field
                        field_score = 1.0 if str(predicted).lower() == str(expected).lower() else 0.0
                    else:
                        # Text similarity
                        expected_words = set(expected.lower().split())
                        predicted_words = set(predicted.lower().split())
                        if expected_words:
                            overlap = len(expected_words.intersection(predicted_words))
                            field_score = min(1.0, overlap / len(expected_words))
                        else:
                            field_score = 0.5  # Partial credit
                else:
                    # Partial credit for having content when no ground truth
                    field_score = 0.5
            else:
                # No prediction made
                field_score = 0.0
                
            weighted_score += field_score * weight
        
        # Handle boolean field separately
        if hasattr(example, 'linksToCorruption') and hasattr(pred, 'linksToCorruption'):
            expected_bool = getattr(example, 'linksToCorruption', False)
            predicted_bool = getattr(pred, 'linksToCorruption', False)
            bool_score = 1.0 if expected_bool == predicted_bool else 0.0
            weighted_score += bool_score * 1.0
            total_weight += 1.0
        
        return weighted_score / total_weight if total_weight > 0 else 0.0
    
    def optimize_with_bootstrap_random_search(self, training_data: List[dspy.Example],
                                            max_labeled_demos=4, max_bootstrapped_demos=4,
                                            num_candidate_programs=10):
        """
        Optimize using BootstrapFewShotWithRandomSearch - good for medium datasets (50+ examples).
        """
        print("Optimizing with BootstrapFewShotWithRandomSearch...")
        
        optimizer = BootstrapFewShotWithRandomSearch(
            metric=self.evaluation_metric,
            max_labeled_demos=max_labeled_demos,
            max_bootstrapped_demos=max_bootstrapped_demos,
            num_candidate_programs=num_candidate_programs,
            num_threads=4
        )
        
        self.optimized_scraper = optimizer.compile(
            self.scraper,
            trainset=training_data
        )
        
        print("BootstrapFewShotWithRandomSearch optimization complete!")
        return self.optimized_scraper
    

    def evaluate_performance(self, test_data: List[dspy.Example]) -> Dict[str, float]:
        """Evaluate the performance of both original and optimized scrapers."""
        
        def evaluate_scraper(scraper, name):
            total_score = 0.0
            for example in test_data:
                try:
                    pred = scraper(text=example.text)
                    score = self.evaluation_metric(example, pred)
                    total_score += score
                except Exception as e:
                    print(f"Error evaluating {name}: {e}")
                    
            avg_score = total_score / len(test_data) if test_data else 0.0
            return avg_score
        
        results = {}
        results['original_scraper'] = evaluate_scraper(self.scraper, "original")
        
        if self.optimized_scraper:
            results['optimized_scraper'] = evaluate_scraper(self.optimized_scraper, "optimized")
            results['improvement'] = results['optimized_scraper'] - results['original_scraper']
        
        return results
    
    def save_optimized_model(self, filepath: str):
        """Save the optimized model for later use."""
        if self.optimized_scraper:
            self.optimized_scraper.save(filepath)
            print(f"Optimized model saved to {filepath}")
        else:
            print("No optimized model to save. Run optimization first.")
    
    def load_optimized_model(self, filepath: str):
        """Load a previously optimized model."""
        try:
            self.optimized_scraper = dspy.ChainOfThought(ExtractIncidentData)
            self.optimized_scraper.load(filepath)
            print(f"Optimized model loaded from {filepath}")
        except Exception as e:
            print(f"Error loading model: {e}")

class ExtractIncidentData(dspy.Signature):
    """Extracts Structured Information from text. Do not imput data only extract from source text."""

    text: str = dspy.InputField()
    category: str = dspy.OutputField(desc="Categorize the type of IUU incident")
    countryOfIncident: str = dspy.OutputField()
    date: str = dspy.OutputField()
    subject: str = dspy.OutputField()
    source: str = dspy.OutputField()
    nameOfOrganizationProvidingInformation: str = dspy.OutputField()
    transportMode: str = dspy.OutputField()
    whereFound: str = dspy.OutputField()
    methodOfConcealment: str = dspy.OutputField()
    outcome: str = dspy.OutputField()
    numberOfPeopleArrested: str = dspy.OutputField()
    numberOfPeopleCharged: str = dspy.OutputField()
    numberOfPeopleFined: str = dspy.OutputField()
    numberOfPeopleImprisioned: str = dspy.OutputField()
    amountOfFines: str = dspy.OutputField()
    currencyOfFines: str = dspy.OutputField()
    fineInUSD: str = dspy.OutputField()
    lengthOfImprisonment: str = dspy.OutputField()
    unitOfTime: str = dspy.OutputField()
    linksToCorruption: bool = dspy.OutputField()
    speciesInvolved: str[2] = dspy.OutputField()
    description: str = dspy.OutputField(desc="Short summary of the incident") 
    

def main():
    """Main function to run the NewsScraper."""
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    scraper = NewsScraper(model='openai/gpt-4o-mini', api_key=api_key)

    train_data = json.load(open(r'DSPy/train_data.json', 'r'))

    training_examples = scraper.create_training_data(train_data)

    scraper.optimize_with_bootstrap_random_search(training_examples)

    scraper.save_optimized_model(r'DSPy/optimized_iuu_incident_scraper.json')

    test_data = json.load(open(r'DSPy/test_data.json', 'r'))
    test_examples = scraper.create_training_data(test_data)

    test_results = scraper.evaluate_performance(test_examples)
    print("Performance Results:", test_results)

if __name__ == "__main__":
    main()