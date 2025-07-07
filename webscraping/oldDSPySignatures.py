from dspy import Signature, InputField, OutputField
from typing import List
from webscraping.schemas import Species

class ExtractIncidentTrafficHeaders(Signature):
    """Extracts Structured Information from text. Do not imput data only extract from source text."""

    text: str = InputField()
    category: str = OutputField(desc="Categorize the type of IUU incident")
    countryOfIncident: str = OutputField()
    date: str = OutputField()
    subject: str = OutputField()
    source: str = OutputField()
    nameOfOrganizationProvidingInformation: str = OutputField()
    transportMode: str = OutputField()
    whereFound: str = OutputField()
    methodOfConcealment: str = OutputField()
    outcome: str = OutputField()
    numberOfPeopleArrested: str = OutputField()
    numberOfPeopleCharged: str = OutputField()
    numberOfPeopleFined: str = OutputField()
    numberOfPeopleImprisioned: str = OutputField()
    amountOfFines: str = OutputField()
    currencyOfFines: str = OutputField()
    fineInUSD: str = OutputField()
    lengthOfImprisonment: str = OutputField()
    unitOfTime: str = OutputField()
    linksToCorruption: bool = OutputField()
    speciesInvolved: List[Species] = OutputField()
    description: str = OutputField(desc="Short summary of the incident")