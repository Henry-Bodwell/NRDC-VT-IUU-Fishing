import dspy
import logging

logger = logging.getLogger(__name__)


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
