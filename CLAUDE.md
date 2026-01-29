# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Issue Tracking (Beads)

This project uses **bd** (beads) for issue tracking. Issues live in the repo alongside code.

```bash
bd ready                              # Find available work
bd show <id>                          # View issue details
bd create "Description"               # Create new issue
bd update <id> --status in_progress   # Claim work
bd close <id>                         # Complete work
bd sync                               # Sync with git
```

### Session Completion Checklist

When ending a work session, complete ALL steps:

1. **File issues** for any remaining/follow-up work (`bd create`)
2. **Run quality gates** if code changed (tests, linters)
3. **Update issue status** - close finished, update in-progress (`bd close`/`bd update`)
4. **Push to remote**:
   ```bash
   git pull --rebase && bd sync && git push
   git status  # Must show "up to date with origin"
   ```
5. **Hand off** - Provide context for next session

**Critical**: Work is NOT complete until `git push` succeeds.

---
## Style Guide

 - Adhere to Black formatting
 - NEVER USE EMOJIs, If needed use Unicode characters 

## Project Overview

IUU (Illegal, Unreported, and Unregulated) Fishing incident tracking system. Uses AI/ML (DSPy) to extract structured information from news articles, PDFs, and other sources, storing them in MongoDB with full audit trails.

## Development Commands

### Running the Application
```bash
# Docker Compose (recommended)
docker compose up

# Development mode with auto-reload
uvicorn app.main:app --reload
```

### Environment Variables
Create a `.env` file with:
- `MONGO_URI`: MongoDB connection string (required)
- `OPENAI_API_KEY`: OpenAI API key for DSPy analysis (required)
- `FRONTEND_PORT`: Frontend port for CORS (default: 4000)

### Testing
```bash
# Integration test for API filters (requires running server)
python test_filters.py
```

---

## Architecture

### Core Pipeline Flow
1. **Content Extraction** (`app/dspy_files/content_extraction.py`): Extracts text from URLs, PDFs, or raw text
2. **Source Scope Classification** (`app/dspy_files/source_scope.py`): Classifies as "Single Incident", "Multiple Incidents", "Industry Overview", or "Unrelated"
3. **Analysis Pipeline** (`app/dspy_files/analysis_pipeline.py`): Routes to appropriate analysis module
4. **Analysis Modules** (`app/dspy_files/modules.py`): DSPy-based structured extraction
5. **Postprocessing** (`app/dspy_files/postprocessing.py`): Formats data into database models
6. **Service Layer** (`app/service/`): Business logic and database operations

### Data Models

Three main document types (MongoDB via Beanie ODM):
- **Source** (`app/models/sources.py`): Raw article/document with text, URL, metadata
- **IncidentReport** (`app/models/incidents.py`): Structured IUU incident data
- **IndustryOverview** (`app/models/incidents.py`): Industry trends/patterns analysis

All inherit from **AuditedDocument** (`app/audit/base.py`) for automatic audit logging.

### Relationships

- **Source <-> IncidentReport**: Many-to-many via `source.incidents` and `incident.sources`
- **Source -> IndustryOverview**: One-to-one via `source.overview`
- **IncidentReport -> Source**: Has one `primary_source` link

**IMPORTANT**: Always use helper methods to maintain relationship integrity:
```python
await incident.add_source(source, is_primary=True)
await incident.remove_source(source)
# Never directly modify incident.sources or source.incidents
```

### Service Layer

All database operations go through `app/service/`:
- **IncidentService**: Full analysis pipeline + CRUD for incidents
- **SourceService**: CRUD for sources
- **OverviewService**: CRUD for industry overviews

### Audit System

The audit system (`app/audit/`) tracks all document changes:
- **Context-based user tracking** (`context.py`): Associates changes with users
- **Multiple diff strategies** (`strategies.py`): JSON patches, text diffs, reference tracking
- **AuditLog model** (`models.py`): Stores change history with versioning

**Critical**: Wrap updates with audit context:
```python
from app.audit.context import AuditContext

with AuditContext.with_user(user_id):
    await IncidentService.update_report(report_id, {"verified": True})
```

---

## API Endpoints

All routes under `/api` prefix (`app/routes.py`):

| Method         | Endpoint                  | Description                |
| -------------- | ------------------------- | -------------------------- |
| POST           | `/api/incidents`          | Create from URL/text/PDF   |
| GET            | `/api/incidents`          | List with filtering        |
| GET/PUT/DELETE | `/api/incidents/{id}`     | Single incident CRUD       |
| GET            | `/api/sources`            | List sources               |
| GET/PUT/DELETE | `/api/sources/{id}`       | Single source CRUD         |
| GET            | `/api/overviews`          | List overviews             |
| GET/PUT/DELETE | `/api/overviews/{id}`     | Single overview CRUD       |
| GET            | `/api/logs`               | All audit logs             |
| GET            | `/api/logs/{document_id}` | Logs for specific document |

---

## Key Implementation Details

### Deduplication
- **Sources**: `article_hash` (SHA256 of article_text)
- **Incidents**: `incident_fingerprint` (SHA256 of vessel_name + event_date + event_location)

### Status Values
- `"extracted"`: Automatically created from analysis
- `"user_input"`: Manually created by user
- `"modified"`: Edited after creation

### IUU Classification Categories
1. Illegal Fishing
2. Illegal Fishing Associated Activities
3. Unreported Catch
4. Unreported Catch Associated Activities
5. Unregulated Actors
6. Unregulated Areas or Stocks
7. Seafood Fraud or Mislabeling
8. Forced Labor or Labor Abuse
9. Circumventing Prohibitions or Sanctions
10. Illegal Aquacultural Practices

---

## Common Patterns

### Creating an Incident from URL
```python
from app.service.incident_service import IncidentService

output = await IncidentService.create_report_from_url("https://example.com/article")
# Returns PipelineOutput with status, source, incidents, and/or industry_overview
```

### WebScraper Usage
```bash
# Import articles to tracking database
python webScraper/upload_scraped_data.py --import

# Upload scraped articles
python webScraper/upload_scraped_data.py --auth-token YOUR_TOKEN --batch-size 10

# Check processing statistics
python webScraper/upload_scraped_data.py --stats
```

---

## Branch Information

- **Current branch**: `refactor`
- **Main branch**: `main`
