"""Retrieval-augmented generation (RAG) support for large-document ingestion.

This package adds token-aware chunking, a persistent vector store (Qdrant),
category-scoped retrieval, and map/reduce incident segmentation so that long
articles and papers are processed by retrieving only the relevant chunks per
extractor instead of feeding the entire document to every DSPy call.
"""
