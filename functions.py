from apis import get_name_pairs


def verify_sci_name(common_name: str, predicted_sci_name: str) -> bool:
    """
    Verify if the predicted scientific name matches any scientific name for the given common name.
    
    Args:
        common_name (str): The common name of the species.
        predicted_sci_name (str): The predicted scientific name to verify.
        
    Returns:
        bool: True if the predicted scientific name matches any known scientific names, False otherwise.
    """
    name_pairs = get_name_pairs(common_name)
    for sci_name, _ in name_pairs:
        if sci_name.lower() == predicted_sci_name.lower():
            return True
    return False