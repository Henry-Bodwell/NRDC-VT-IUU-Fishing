import pandas as pd


isscaap = pd.read_csv("data/isscaap.csv")
asfis = pd.read_csv("data/ASFIS.csv")


joined_df = pd.merge(
    isscaap,
    asfis,
    left_on="isscaap_code",
    right_on="ISSCAAP_Group",
    how="left",
    suffixes=(".isscaap", ".asfis"),
)

joined_df.to_csv("data/joined_isscaap_asfis.csv", index=False)
