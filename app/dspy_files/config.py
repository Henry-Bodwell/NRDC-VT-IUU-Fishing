import dspy


def setup_dspy(model: str = "openai/gpt-4o-mini", api_key: str = None) -> dspy.LM:
    """Configures and returns the DSPy language model."""
    lm = dspy.LM(model, api_key=api_key)
    dspy.settings.configure(lm=lm)
    return lm
