import dspy
import json
from dotenv import dotenv_values
from app.models.article_models import BaseIntake
from app.models.iuu_models import IncidentReport
from app.dspy_files.modules import IncidentAnalysisModule, IndustryOverviewModule
from app.dspy_files.signatures import ArticleClassificationSignature
import app.dspy_files.functions as fn
from app.dspy_files.scraper import ArticleExtractionPipeline


class NewsAnalysisTool:
    def __init__(self, model="openai/gpt-4o-mini", api_key: str = None):
        """Initialize the NewsScraper with gpt 4o mini."""
        self.lm = dspy.LM(model, api_key=api_key)
        dspy.settings.configure(lm=self.lm)

        self.scraper = ArticleExtractionPipeline()
        self.analysisTool = IncidentAnalysisModule()
        self.articleClassificationTool = dspy.ChainOfThought(
            ArticleClassificationSignature
        )
        self.industryOverviewTool = IndustryOverviewModule()
        self.optimized_analysisTool = None

    async def extract_from_text(
        self, article_text: str, url: str = ""
    ) -> dspy.Prediction | None:
        """
        Extract structured information from the provided text, if relevant.

        Returns None if the article is unrelated to IUU fishing incidents.
        """
        try:
            intake = BaseIntake(url=url, article_text=article_text)

            classification_pred = await self.articleClassificationTool.acall(
                intake=intake
            )
            classification_result = classification_pred.classification

            # --- Check the classification type ---
            if classification_result.articleType == "Unrelated to IUU Fishing":
                print(
                    f"Article is unrelated to IUU Fishing. Retaining source information."
                )
                # Return a prediction with just the source info and classification
                return dspy.Prediction(
                    url=intake.url,
                    article_text=intake.article_text,
                    classification=classification_result,
                    extracted_data=None,
                )

            elif classification_result.articleType == "Industry Overview":
                print(f"Article is Industry Overview. Running specialized extraction.")
                # TODO: Replace with your industry overview extraction tool
                prediction = await self.industryOverviewTool.acall(intake=intake)
                return prediction

            else:
                # --- Proceed with normal IUU incident analysis ---
                # TODO implement better multiple incident extraction
                print(
                    f"Article type {classification_result.articleType} detected. Running incident analysis."
                )
                prediction = await self.analysisTool.acall(intake=intake)
                return prediction

        except Exception as e:
            print(f"Error in extract_from_text: {e}")
            return None

    async def extract_from_url(self, url: str) -> dspy.Prediction:
        """Extract structured information from a news article at the given URL."""
        article_object = await self.scraper.process_url(url=url)

        article_text = article_object.clean_content
        return await self.extract_from_text(article_text, url)

    async def extract_from_pdf(self, pdf_path: str) -> dspy.Prediction:
        """Extract structured information from a PDF file."""
        text = fn.read_pdf(pdf_path)
        return await self.extract_from_text(text)

    async def extract_from_image(
        self, image_path: str, language: str = "eng"
    ) -> dspy.Prediction:
        """Extract structured information from an image file."""
        text = fn.read_image(image_path, language=language)
        return await self.extract_from_text(text)

    def format_results(self, analysis_output: dict) -> IncidentReport:

        # Helper function to convert Pydantic objects to dict
        def convert_to_dict(obj):
            if hasattr(obj, "model_dump"):  # Pydantic v2
                return obj.model_dump()
            elif hasattr(obj, "dict"):  # Pydantic v1
                return obj.dict()
            else:
                return obj

        final_results = {
            "source": {
                "url": analysis_output.get("url", None),
                "article_text": analysis_output.get("article_text", None),
            },
            "extracted_information": convert_to_dict(
                analysis_output.get("parsed_data", None)
            ),
            "incident_classification": convert_to_dict(
                analysis_output.get("classification", None)
            ),
        }
        return IncidentReport(**final_results)

    def verify_results(self, formatted_results: IncidentReport) -> IncidentReport:
        """
        Verify the scientific names in the analysis output against known species names.
        Returns the formatted_results dict with verification status added to each species.
        """
        if not isinstance(formatted_results, dict):
            print("Error: formatted_results is not a dictionary")
            return formatted_results  # Return the original data instead of None

        extracted_info = formatted_results.get("extracted_information", {})
        if not extracted_info:
            print("Warning: No extracted_information found in analysis output.")
            return (
                formatted_results  # Return original data instead of raising exception
            )

        species_list = extracted_info.get("speciesInvolved", [])
        if not species_list:
            print("Warning: No species found in extracted information.")
            return formatted_results

        for species in species_list:
            if not isinstance(species, dict):
                print(f"Warning: Species entry is not a dictionary: {species}")
                continue

            common_name = species.get("commonName")
            # Note: You're looking for 'predictedScientificName' but your JSON shows 'scientificName'
            predicted_sci_name = species.get("predictedScientificName") or species.get(
                "scientificName"
            )

            if not common_name or not predicted_sci_name:
                print(
                    f"Missing common name or predicted scientific name for species: {species}"
                )
                species["verified"] = False  # Set to False if data is missing
                continue

            # Verify the scientific name using the functions module
            try:
                is_verified = fn.verify_sci_name(common_name, predicted_sci_name)
                species["verified"] = is_verified
                print(f"Verified {common_name} -> {predicted_sci_name}: {is_verified}")
            except Exception as e:
                print(f"Error verifying {common_name}: {e}")
                species["verified"] = False

        return formatted_results

    async def extract_and_verify(self, url: str) -> IncidentReport:
        """
        Extract structured information from a news article at the given URL and verify the scientific name.
        Returns a dictionary with the extraction results and a boolean verification status.
        """
        analysis_output = await self.extract_from_url(url)
        if not analysis_output:
            return {
                "error": "No relevant information extracted from the article."
            }, False

        formatted_results = self.format_results(analysis_output)
        if not formatted_results:
            return {"error": "Failed to format results."}, False

        extracted_info = formatted_results.get("extracted_information", None)
        if (
            extracted_info
            and isinstance(extracted_info, dict)
            and extracted_info.get("scopeOfArticle")
        ):
            article_type = extracted_info.get("scopeOfArticle")

            if article_type == "Unrelated to IUU Fishing":
                # No verification needed for unrelated articles
                print("Article is unrelated to IUU Fishing. Skipping verification.")
                return formatted_results
            else:
                formatted_results = self.verify_results(formatted_results)
                # print(formatted_results)
                return formatted_results
        else:
            print(
                "No scope of article found in extracted information. Skipping verification."
            )
            return formatted_results


def main():
    """Main function to run the NewsScraper."""
    config = dotenv_values(".env")
    api_key = config["OPENAI_API_KEY"]
    analyzer = NewsAnalysisTool(model="openai/gpt-4o-mini", api_key=api_key)

    # Sample single incident article
    url = "https://cbcgdf.wordpress.com/2024/08/07/beijing-customs-intercepted-at-the-capital-airport-a-box-of-oahu-tree-snail-shells-cbcgdf-expert-shen-yihang-reports/"
    # Sample industry journal
    # url = "https://www.bbc.com/news/articles/cq69e4j6jz8o"
    # Sample unrelated article
    # url = "https://www.amazon.com/Ring-Battery-Doorbell-Head-to-Toe-Video-Satin-Nickel/dp/B0BZWRSRWV?ref=dlx_devic_dg_dcl_B0BZWRSRWV_dt_sl7_a4_pi&th=1"
    analyzer.max_retries = (
        3  # Set the maximum number of retries for species verification
    )
    results = analyzer.extract_and_verify(url)

    if results is None:
        print("No relevant information extracted from the article.")
    else:
        with open("news_analysis_results_unrelated_test.json", "w") as f:
            json.dump(results, f, indent=4)

    # print(analyzer.fetch_article_from_url(url=url))


if __name__ == "__main__":
    main()
