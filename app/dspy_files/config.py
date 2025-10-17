import dspy


def setup_dspy(model: str = "openai/gpt-4o-mini", api_key: str = None) -> dspy.LM:
    """Creates and returns a DSPy language model without configuring global settings.

    In async environments, use dspy.context(lm=lm) instead of dspy.settings.configure()
    to set the language model for specific async tasks.
    """
    # Note: Don't use response_format={"type": "json_object"} with DSPy's default adapter
    # DSPy uses its own formatting with field markers like [[ ## field_name ## ]]
    lm = dspy.LM(model, api_key=api_key)
    return lm
