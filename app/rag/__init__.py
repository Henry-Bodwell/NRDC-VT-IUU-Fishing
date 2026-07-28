"""Retrieval-augmented generation (RAG) support for large-document ingestion.

This package adds token-aware chunking, a persistent vector store (Qdrant),
category-scoped retrieval, and map/reduce incident segmentation so that
articles and papers are processed by retrieving only the relevant chunks per
extractor instead of feeding the entire document to every DSPy call.

Incident extraction takes this path for every source regardless of size; the
full-text path remains only as the fallback for when indexing is unavailable.
Scope classification and industry overviews still use the full text.
"""
