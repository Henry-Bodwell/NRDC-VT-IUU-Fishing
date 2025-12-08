"""
Shared utilities and clients for IUU incident processing.

This package contains reusable components used across newsapi and webscraper modules.
"""

from .pipeline_client import (
    submit_article_to_pipeline,
    ProcessingTracker,
    process_batch_with_concurrency,
    print_processing_stats,
)

__all__ = [
    "submit_article_to_pipeline",
    "ProcessingTracker",
    "process_batch_with_concurrency",
    "print_processing_stats",
]
