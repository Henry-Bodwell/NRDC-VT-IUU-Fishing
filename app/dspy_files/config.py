import dspy


def setup_dspy(model: str = "openai/gpt-4o-mini", api_key: str = None) -> dspy.LM:
    """Configures and returns the DSPy language model."""
    # Note: Don't use response_format={"type": "json_object"} with DSPy's default adapter
    # DSPy uses its own formatting with field markers like [[ ## field_name ## ]]
    lm = dspy.LM(model, api_key=api_key)

    dspy.settings.configure(lm=lm)
    return lm
