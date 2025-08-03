import asyncio
import hashlib
from beanie import init_beanie
from dotenv import dotenv_values
from pymongo import AsyncMongoClient
from app.dspy_files.config import setup_dspy
from app.dspy_files.content_extraction import ContentExtractor
from app.dspy_files.pipeline import AnalysisPipeline
from app.dspy_files.postprocessing import format_report, verify_species_in_report
from app.models.incidents import IncidentReport


async def run_full_analysis_from_url(url: str) -> IncidentReport | None:
    """
    Orchestrates the end-to-end process of URL -> Text -> Analysis -> Format -> Verify.
    """
    # 1. Initialize components
    extractor = ContentExtractor()
    pipeline = AnalysisPipeline()

    # 2. Extract content
    try:
        article_text, source_url = await extractor.from_url(url)
    except Exception as e:
        print(f"Failed to extract content from {url}: {e}")
        return None

    article_hash = hashlib.sha256(article_text.encode()).hexdigest()
    try:
        text_exists = await IncidentReport.find(
            IncidentReport.source.article_hash == article_hash
        ).first_or_none()

        if text_exists:
            print("Article text already exists in the database. Skipping analysis.")
            return text_exists
    except Exception as e:
        print(f"Error checking for existing article text: {e}")
        return None

    # 3. Run analysis
    prediction = await pipeline.run(article_text, source_url)
    if not prediction:
        print("Analysis pipeline returned no result.")
        return None

    # 4. Format the raw prediction into a structured report
    report = format_report(prediction)
    if not report:
        print("Failed to format the analysis prediction.")
        return None

    # 5. Verify data if the article is relevant
    # The classification is now inside the report object
    classification = report.extracted_information.scopeOfArticle
    if not "Unrelated" in classification:
        verified_report = verify_species_in_report(report)
        return verified_report
    else:
        print("Article is not an IUU incident report. Skipping species verification.")
        return report


async def main():
    """Main function to run the NewsScraper."""
    config = dotenv_values(".env")
    api_key = config["OPENAI_API_KEY"]
    setup_dspy(api_key=api_key)
    uri = config["MONGO_URI"]
    # Sample single incident article
    url = "https://cbcgdf.wordpress.com/2024/08/07/beijing-customs-intercepted-at-the-capital-airport-a-box-of-oahu-tree-snail-shells-cbcgdf-expert-shen-yihang-reports/"
    # Sample industry journal
    # url = "https://www.bbc.com/news/articles/cq69e4j6jz8o"
    # Sample unrelated article
    # url = "https://www.amazon.com/Ring-Battery-Doorbell-Head-to-Toe-Video-Satin-Nickel/dp/B0BZWRSRWV?ref=dlx_devic_dg_dcl_B0BZWRSRWV_dt_sl7_a4_pi&th=1"

    client = AsyncMongoClient(uri)

    await init_beanie(
        database=client.get_database("iuuIncidents"),  # Use get_database() for clarity
        document_models=[IncidentReport],  # Pass all Beanie Documents here
    )
    print("Database initialized successfully.")

    report = await run_full_analysis_from_url(url)
    if report:
        print("\n--- Final Report ---")
        # Use model_dump_json for clean printing of Pydantic model
        print(report.model_dump_json(indent=2))


if __name__ == "__main__":

    asyncio.run(main())
