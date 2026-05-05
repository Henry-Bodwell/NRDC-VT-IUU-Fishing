"""
We need two queries:
    Count for each KDE / Count of Incidents -> by IUU sub/type?
    Rate of non null KDE Group, can we use infomration presence? again by IUU sub type 
"""
import beanie
import pandas as pandas
from app.models import IncidentReport
from app.database import init_db
from app.models.iuu_classifications import (
    IncidentClassification
)
import json


await init_db()

async def kde_counts(iuuType: Optional[IncidentClassification]=None):
    """Get count and non-null rate for all fields in a Beanie document."""
    total = await IncidentReport.count()
    if total == 0:
        return {}
    fields = IncidentReport.extracted_information.model_fields.keys()
    
    pipeline = [
        *([ {"$match": match} ] if match else []),
        {
            "$group": {
                "_id": None,
                "total": {"$sum": 1},
                **{
                    f"{field}_count": {
                        "$sum": {
                            "$cond": [
                                {"$gt": [f"${field}", None]},
                                1,
                                0
                            ]
                        }
                    }
                    for field in fields
                }
            }
        }
    ]

    results = await model.aggregate(pipeline).to_list()
    if not results:
        return {}

    row = results[0]
    total = row["total"]
    return {
        field: {
            "count": row[f"{field}_count"],
            "non_null_rate": round(row[f"{field}_count"] / total, 4),
        }
        for field in fields
    }

if __name__ =="__main__":
    res = await kde_counts()
    print(json.dumps(res, indent=2))