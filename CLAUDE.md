# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an IUU (Illegal, Unreported, and Unregulated) Fishing incident tracking and analysis system. The project uses AI/ML to extract structured information about fishing incidents from news articles, PDFs, and other sources, storing them in MongoDB with full audit trails.

## Development Commands

### Running the Application
```bash
# Start with Docker Compose (recommended for development)
docker-compose up

# Run locally (requires MongoDB running on localhost:27017)
MONGO_URI=mongodb://localhost:27017/iuuIncidents uvicorn app.main:app --host 0.0.0.0 --port 8000

# Run in development mode with auto-reload
uvicorn app.main:app --reload
```

### Environment Variables
Create a `.env` file with:
- `MONGO_URI`: MongoDB connection string (required)
- `OPENAI_API_KEY`: OpenAI API key for DSPy analysis (required)
- `FRONTEND_PORT`: Frontend port for CORS (default: 4000)

### Testing
```bash
# Run tests (basic test structure exists in test/)
python -m pytest test/

# Test API endpoints
python test/apiTest.py
```

## Architecture

### Core Pipeline Flow
1. **Content Extraction** (`app/dspy_files/content_extraction.py`): Extracts text from URLs, PDFs, or raw text
2. **Source Scope Classification** (`app/dspy_files/source_scope.py`): Classifies articles as "Single Incident", "Multiple Incidents", "Industry Overview", or "Unrelated"
3. **Analysis Pipeline** (`app/dspy_files/analysis_pipeline.py`): Routes to appropriate analysis module based on classification
4. **Analysis Modules** (`app/dspy_files/modules.py`): Uses DSPy to extract structured data
5. **Postprocessing** (`app/dspy_files/postprocessing.py`): Formats extracted data into database models
6. **Service Layer** (`app/service/`): Handles business logic and database operations

### Data Models

**Three main document types (all in MongoDB via Beanie ODM):**
- **Source** (`app/models/articles.py`): Raw article/document with text, URL, metadata, and article_scope classification
- **IncidentReport** (`app/models/incidents.py`): Structured IUU incident data with vessel info, species, crew, event details, etc.
- **IndustryOverview** (`app/models/incidents.py`): Analysis of industry trends/patterns (not specific incidents)

All three inherit from **AuditedDocument** (`app/audit/base.py`) which provides automatic audit logging.

### Audit System

The audit system (`app/audit/`) tracks all document changes with field-level granularity:
- **Context-based user tracking** (`app/audit/context.py`): Uses context manager to associate changes with users
- **Multiple diff strategies** (`app/audit/strategies.py`): JSON patches for structured data, text diffs for large text fields, reference tracking for relationships
- **AuditLog model** (`app/audit/models.py`): Stores change history with version tracking

**Critical**: When updating documents, use the service layer methods which handle audit context properly. Updates should be wrapped with `AuditContext.with_user(user_id)` when user information is available.

### Relationships

Sources, Incidents, and Overviews have bidirectional relationships:
- **Source ↔ IncidentReport**: Many-to-many via `source.incidents` and `incident.sources`
- **Source → IndustryOverview**: One-to-one via `source.overview`
- **IncidentReport → Source**: Has one `primary_source` link

**IMPORTANT**: Always use helper methods (`incident.add_source()`, `incident.remove_source()`) to maintain relationship integrity. Direct manipulation of relationship fields can break bidirectional links.

### Service Layer Pattern

All database operations go through service classes in `app/service/`:
- **IncidentService** (`incident_service.py`): Orchestrates full analysis pipeline and CRUD for incidents
- **SourceService** (`source_service.py`): CRUD operations for sources
- **OverviewService** (`overview_service.py`): CRUD operations for industry overviews

Services handle:
- Relationship management (linking sources to incidents)
- Audit logging context
- Data validation and filtering
- Error handling and logging

### DSPy Integration

This project uses DSPy (Declarative Self-improving Language Programs) for structured extraction:
- **Signatures** (`app/dspy_files/signatures.py`): Define input/output schemas for LLM calls
- **Modules** (`app/dspy_files/modules.py`): Combine signatures into reusable components
- **Config** (`app/dspy_files/config.py`): DSPy/LLM configuration
- DSPy is configured with OpenAI models (default: gpt-4o-mini)

### WebScraper Module (In Development)

Located in `webScraper/`, this is a new configurable web scraping framework:
- **Base classes** (`scrapers/base_scraper.py`, `scrapers/generic_scraper.py`): Extensible scraper architecture
- **Site configs** (`config/site_config.py`): Per-site scraping rules
- **Config builder** (`utils/config_builder.py`): Programmatic configuration generation

This module is separate from the main DSPy-based content extraction and appears to be under active development.

### API Endpoints

All routes are in `app/routes.py` under `/api` prefix:
- **POST /api/incidents**: Create incident from URL/text/PDF
- **GET /api/incidents**: List with filtering (source_type, verified, IUU_type, status)
- **GET /api/incidents/{report_id}**: Get specific incident
- **PUT /api/incidents/{report_id}**: Update incident
- **DELETE /api/incidents/{report_id}**: Delete incident
- **GET /api/sources**: List sources with filters
- **GET /api/sources/{source_id}**: Get specific source
- **PUT /api/sources/{source_id}**: Update source
- **DELETE /api/sources/{source_id}**: Delete source
- **GET /api/overviews**: List overviews
- **GET /api/overviews/{overview_id}**: Get specific overview
- **PUT /api/overviews/{overview_id}**: Update overview
- **DELETE /api/overviews/{overview_id}**: Delete overview
- **GET /api/logs**: Get all audit logs
- **GET /api/logs/{document_id}**: Get logs for specific document

## Important Implementation Details

### Deduplication
- Sources use `article_hash` (SHA256 of article_text) to prevent duplicate articles
- IncidentReports use `incident_fingerprint` (SHA256 of vessel_name + event_date + event_location)
- Both have unique indexes in MongoDB

### Content Types
The POST /api/incidents endpoint accepts:
- **JSON**: `{"url": "...", "user_id": "..."}` or `{"text": "...", "user_id": "..."}`
- **Multipart form-data**: PDF file upload

### IUU Classification Schema
Incidents are classified into 10 main categories defined in `app/models/incidents.py`:
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

Each has specific subtypes defined in the `subtype_behavior` string.

### Verification Pattern
Most nested models (Species, CrewMember, EventData, etc.) have a `verified` boolean field (defaults to False) to track human verification status. The top-level IncidentReport also has a `verified` field.

### Status Tracking
Both Source and IncidentReport have a `status` field:
- "extracted": Automatically created from analysis
- "user_input": Manually created by user
- "modified": Edited after creation

## Logging

Structured logging is configured in `app/logging.py`. All service operations and pipeline stages log extensively. Check logs for:
- Pipeline stage transitions
- Database save operations
- Analysis failures
- Duplicate detection

## Common Patterns

### Creating an Incident from URL
```python
from app.service.incident_service import IncidentService

output = await IncidentService.create_report_from_url("https://example.com/article")
# Returns PipelineOutput with status, source, incidents, and/or industry_overview
```

### Updating with Audit Context
```python
from app.audit.context import AuditContext
from app.service.incident_service import IncidentService

with AuditContext.with_user(user_id):
    await IncidentService.update_report(report_id, {"verified": True})
```

### Managing Source-Incident Relationships
```python
# Always use helper methods
await incident.add_source(source, is_primary=True)
await incident.remove_source(source)
# Never directly modify incident.sources or source.incidents
```

## Branch Information

- Current branch: `webscraper` (in development)
- Main branch: `main`
- The webscraper branch contains the new webScraper module