from pydantic import BaseModel, Field, HttpUrl
import hashlib


class ArticleData(BaseModel):
    """Pydantic model for validated article data"""

    url: HttpUrl
    title: str | None = Field(default=None)
    raw_html: str | None = Field(default=None)
    clean_content: str | None = Field(default=None)


class BaseIntake(BaseModel):
    url: str = Field(..., description="URL of the article to analyze.")
    article_text: str = Field(
        ..., description="Text content of the article to analyze."
    )
    article_hash: str = Field(
        default="", description="Hash of article text for deduplication"
    )
    language: str = Field(..., description="Language of the article")

    def __init__(self, **data):
        super().__init__(**data)
        if not self.article_hash:
            self.article_hash = hashlib.sha256(self.article_text.encode()).hexdigest()
