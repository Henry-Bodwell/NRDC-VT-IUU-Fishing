"""
We need two queries:
    Count for each KDE / Count of Incidents -> by IUU sub/type?
    Rate of non null KDE Group, can we use infomration presence? again by IUU sub type
"""
import asyncio
import json
from typing import Optional

from app.database import init_db
from app.models import IncidentReport
from app.models.iuu_classifications import IncidentClassification


async def kde_counts(iuuType: Optional[IncidentClassification] = None):
    """Get count and non-null rate for all fields in a Beanie document."""
    match = {"incident_classification.iuuClassifications": iuuType.value} if iuuType else None
    fields = IncidentReport.extracted_information.model_fields.keys()

    pipeline = [
        *([{"$elemMatch": match}] if match else []),
        {
            "$group": {
                "_id": None,
                "total": {"$sum": 1},
                **{
                    f"{field}_count": {
                        "$sum": {
                            "$cond": [
                                {"$gt": [f"$extracted_information.{field}", None]},
                                1,
                                0,
                            ]
                        }
                    }
                    for field in fields
                },
            }
        },
    ]

    results = await IncidentReport.aggregate(pipeline).to_list()
    if not results:
        return {}

    row = results[0]
    total = row["total"]
    if total == 0:
        return {}
    return {
        field: {
            "count": row[f"{field}_count"],
            "non_null_rate": round(row[f"{field}_count"] / total, 4),
        }
        for field in fields
    }


async def main():
    await init_db()
    res = await kde_counts()
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    asyncio.run(main())