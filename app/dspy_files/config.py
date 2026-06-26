import os
import dspy
import logging

logger = logging.getLogger(__name__)

# ── RAG / chunking configuration ────────────────────────────────────────────
# Embedding model used to vectorize document chunks for retrieval.
EMBEDDING_MODEL: str = "text-embedding-3-small"

# Documents whose token count is >= this threshold are routed through the
# chunking + RAG extraction path. Shorter documents keep the (cheaper, proven)
# full-text path. Overridable via the RAG_TOKEN_THRESHOLD environment variable.
RAG_TOKEN_THRESHOLD: int = int(os.getenv("RAG_TOKEN_THRESHOLD", "6000"))

# Encoding used for token counting / gating decisions.
_TOKEN_COUNT_MODEL: str = "gpt-4o-mini"


def count_tokens(text: str, model: str = _TOKEN_COUNT_MODEL) -> int:
    """Count the number of tokens in ``text`` for the given model's encoding.

    Falls back to the ``cl100k_base`` encoding for unknown models. Returns 0 for
    empty input.
    """
    if not text:
        return 0

    import tiktoken

    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))


def should_use_rag(text: str, threshold: int | None = None) -> bool:
    """Decide whether ``text`` is large enough to warrant the chunking/RAG path.

    Returns True when the token count is >= ``threshold`` (or the module-level
    ``RAG_TOKEN_THRESHOLD`` when ``threshold`` is None).
    """
    limit = threshold if threshold is not None else RAG_TOKEN_THRESHOLD
    return count_tokens(text) >= limit


def make_embedder(
    model: str = EMBEDDING_MODEL, api_key: str | None = None
) -> dspy.Embedder:
    """Construct a DSPy embedder for the configured embedding model.

    Mirrors :func:`setup_dspy`: returns the embedder without mutating global
    DSPy settings so it can be used inside ``dspy.context`` scopes.
    """
    kwargs: dict = {}
    if api_key is not None:
        kwargs["api_key"] = api_key
    return dspy.Embedder(model, **kwargs)


def inspect_dspy_history(n: int = 3):
    """
    Inspect the last n DSPy LM interactions to debug issues.

    Args:
        n: Number of recent interactions to show (default: 3)
    """
    try:
        logger.info(f"=== Inspecting last {n} DSPy interactions ===")
        dspy.inspect_history(n=n)
    except Exception as e:
        logger.error(f"Failed to inspect DSPy history: {e}")


def setup_dspy(
    model: str = "openai/gpt-4o-mini",
    api_key: str = None,
    max_tokens: int = 8000,
    temperature: float = 0.1,
) -> dspy.LM:
    """Creates and returns a DSPy language model without configuring global settings.

    In async environments, use dspy.context(lm=lm) instead of dspy.settings.configure()
    to set the language model for specific async tasks.

    Args:
        model: The model to use (default: openai/gpt-4o-mini)
        api_key: OpenAI API key
        max_tokens: Maximum tokens for response (default: 8000)
        temperature: Sampling temperature 0.0-2.0 (default: 0.3)
                    Higher values = more random, lower = more deterministic
    """
    # Note: Don't use response_format={"type": "json_object"} with DSPy's default adapter
    # DSPy uses its own formatting with field markers like [[ ## field_name ## ]]
    lm = dspy.LM(model, api_key=api_key, max_tokens=max_tokens, temperature=temperature)
    return lm
