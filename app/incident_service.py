from fastapi import File, HTTPException, status
from app.dspy_files.news_analysis import run_full_analysis_from_url
from app.models.incidents import IncidentReport
from app.models.logs import LogContext


def _filter_valid_fields(model_class, updates: dict) -> dict:
    valid_fields = set(model_class.model_fields.keys())
    return {k: v for k, v in updates.items() if k in valid_fields}


class IncidentService:
    """
    Service layer for incident reports. Allows for greater logging
    """

    @staticmethod
    async def create_report_from_url(url: str, context_data: dict) -> IncidentReport:
        context = LogContext(
            user_id=context_data.get("acting_user_id"),
            action="new_report",
            source=context_data.get("source"),
        )

        print(f"Service: Starting analysis for URL: {url}")

        report_object = await run_full_analysis_from_url(url)

        if not report_object:
            print(f"Service: Analysis failed to produce a report for URL: {url}")
            return None

        report_object.set_log_context(context)

        try:
            await report_object.insert()
            print(f"Service: Successfully saved report for URL: {url}")
        except Exception as e:
            print(f"Service: Database save failed for URL {url}: {e}")
            return None

        return report_object

    @staticmethod
    async def create_report_from_file(file: File, context_data: dict) -> IncidentReport:
        context = LogContext(
            user_id=context_data.get("acting_user_id"),
            action="new_report",
            source=context_data.get("source"),
        )

        print(f"Service: Starting analysis for file: {file.filename}")
        return {"status": "error", "detail": "not implemented yet"}

    @staticmethod
    async def update_report(
        report_id: str, update_data: dict, context_data: dict
    ) -> IncidentReport:
        context = LogContext(
            user_id=context_data.get("acting_user_id"),
            action="edit_report",
            source=context_data.get("source"),
        )

        print(f"Service: Updating report {report_id} with data: {update_data}")

        report = await IncidentReport.get(report_id)
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report with ID {report_id} not found.",
            )

        report.set_log_context(context)
        updates = _filter_valid_fields(IncidentReport, update_data)
        for field, value in updates.items():
            setattr(report, field, value)

        report.set_log_context(context)

        try:
            await report.save()
            print(f"Service: Successfully updated report {report_id}")
        except Exception as e:
            print(f"Service: Update failed for report {report_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update the report.",
            )

        return report

    @staticmethod
    async def delete_report(report_id: str, context_data: dict) -> bool:
        context = LogContext(
            user_id=context_data.get("acting_user_id"),
            action="delete_report",
            source=context_data.get("source"),
        )

        print(f"Service: Deleting report {report_id}")

        report = await IncidentReport.get(report_id)
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report with ID {report_id} not found.",
            )

        report.set_log_context(context)

        try:
            await report.delete()
            print(f"Service: Successfully deleted report {report_id}")
        except Exception as e:
            print(f"Service: Deletion failed for report {report_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete the report.",
            )
        return True
