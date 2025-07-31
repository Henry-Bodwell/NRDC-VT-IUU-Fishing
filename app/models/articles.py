from pydantic import BaseModel, Field, HttpUrl


class ArticleData(BaseModel):
    """Pydantic model for validated article data"""

    url: HttpUrl
    title: str | None = Field(default=None)
    raw_html: str | None = Field(default=None)
    clean_content: str | None = Field(default=None)


class BaseIntake(BaseModel):
    """Base model for intake data."""

    url: str = Field(..., description="URL of the article to analyze.")
    article_text: str = Field(
        ..., description="Text content of the article to analyze."
    )
    language: str = Field(..., description="Language of the article")
