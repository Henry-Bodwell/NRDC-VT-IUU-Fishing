import dspy
from app.models.articles import Source
from app.dspy_files.signatures import ArticleClassificationSignature


class SourceScope:
    def __init__(self):
        self.classification_tool = dspy.ChainOfThought(ArticleClassificationSignature)

    async def run(self, source: Source) -> Source:
        """
        Classifies the article and returns the structured source data.
        """
        try:
            if source.article_scope:
                print(
                    f"Article from '{source.url}' already classified as: {source.article_scope.articleType}"
                )
                return source

            classification_pred = await self.classification_tool.acall(intake=source)
            source.article_scope = classification_pred.classification

            print(f"Article classified as: {source.article_scope.articleType} ")
            return source
        except Exception as e:
            print(f"Error during source pipeline for '{source.url}': {e}")
            raise
