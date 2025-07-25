import csv
import torch
import numpy as np
from typing import List, Dict, Tuple, Optional
from collections import defaultdict, Counter
import re

# BERT and transformers
from transformers import (
    AutoTokenizer,
    AutoModel,
    BertTokenizer,
    BertModel,
    AutoModelForMaskedLM,
)

# Traditional NLP libraries
import spacy
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import KMeans
import pandas as pd

# Language detection
from langdetect import detect


def clean_text_for_excel(text: str) -> str:
    """Removes illegal control characters from a string for Excel compatibility."""
    if not isinstance(text, str):
        return text
    # This regex removes most ASCII control characters but keeps tab, newline, etc.
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


class BERTKeywordAnalyzer:
    def __init__(self, model_name: str = "bert-base-multilingual-cased"):
        """
        Initialize BERT-based keyword analyzer.

        Popular multilingual models:
        - 'bert-base-multilingual-cased': 104 languages
        - 'distilbert-base-multilingual-cased': Faster, smaller version
        - 'xlm-roberta-base': 100 languages, often better performance
        - 'microsoft/mdeberta-v3-base': Recent, high-performance model
        """
        self.model_name = model_name
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Using device: {self.device}")

        # Load BERT model and tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name).to(self.device)
        self.model.eval()  # Set to evaluation mode

        # Cache for embeddings to avoid recomputation
        self.embedding_cache = {}

        # Load spaCy for text preprocessing
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except OSError:
            print("Warning: spaCy English model not found. Using basic preprocessing.")
            self.nlp = None

    def get_bert_embeddings(self, texts: List[str], batch_size: int = 16) -> np.ndarray:
        """
        Get BERT embeddings for a list of texts with batching for efficiency.
        """
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]

            # Tokenize batch
            encoded = self.tokenizer(
                batch_texts,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            ).to(self.device)

            # Get embeddings
            with torch.no_grad():
                outputs = self.model(**encoded)
                # Use CLS token embedding or mean pooling
                embeddings = outputs.last_hidden_state.mean(dim=1)  # Mean pooling
                all_embeddings.append(embeddings.cpu().numpy())

        return np.vstack(all_embeddings)

    def extract_candidate_phrases(
        self, text: str, max_phrase_length: int = 3
    ) -> List[str]:
        """
        Extract candidate phrases using linguistic patterns.
        """
        candidates = []

        if self.nlp:
            doc = self.nlp(text)

            # Extract noun phrases
            for chunk in doc.noun_chunks:
                if len(chunk.text.split()) <= max_phrase_length:
                    candidates.append(chunk.text.lower().strip())

            # Extract named entities
            for ent in doc.ents:
                if len(ent.text.split()) <= max_phrase_length:
                    candidates.append(ent.text.lower().strip())

            # Extract important single words
            for token in doc:
                if (
                    token.pos_ in ["NOUN", "PROPN", "ADJ"]
                    and not token.is_stop
                    and len(token.text) > 2
                ):
                    candidates.append(token.lemma_.lower())
        else:
            # Basic pattern-based extraction if spaCy not available
            # Extract sequences of capitalized words (likely proper nouns)
            capitalized_pattern = r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b"
            candidates.extend(re.findall(capitalized_pattern, text))

            # Extract important words (simple heuristic)
            words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
            candidates.extend(words)

        # Remove duplicates and filter
        candidates = list(set(candidates))
        candidates = [c for c in candidates if len(c.strip()) > 2]

        return candidates

    def bert_keyword_extraction(
        self, text: str, top_k: int = 10, diversity_threshold: float = 0.7
    ) -> List[Tuple[str, float]]:
        """
        Extract keywords using BERT embeddings and semantic similarity.
        """
        # Extract candidate phrases
        candidates = self.extract_candidate_phrases(text, 1)

        if len(candidates) < 2:
            return []

        # Get embeddings for document and candidates
        doc_embedding = self.get_bert_embeddings([text])
        candidate_embeddings = self.get_bert_embeddings(candidates)

        # Calculate similarity between document and candidates
        similarities = cosine_similarity(doc_embedding, candidate_embeddings)[0]

        # Rank candidates by similarity
        candidate_scores = list(zip(candidates, similarities))
        candidate_scores.sort(key=lambda x: x[1], reverse=True)

        # Apply diversity filtering to avoid redundant keywords
        selected_keywords = []
        selected_embeddings = []

        for candidate, score in candidate_scores:
            if len(selected_keywords) >= top_k:
                break

            # Check diversity with already selected keywords
            candidate_emb = candidate_embeddings[candidates.index(candidate)]

            if not selected_embeddings:
                selected_keywords.append((candidate, float(score)))
                selected_embeddings.append(candidate_emb)
            else:
                # Calculate similarity with already selected keywords
                max_sim = max(
                    cosine_similarity([candidate_emb], selected_embeddings)[0]
                )

                if max_sim < diversity_threshold:
                    selected_keywords.append((candidate, float(score)))
                    selected_embeddings.append(candidate_emb)

        return selected_keywords

    def bert_masked_language_modeling(
        self, text: str, top_k: int = 5
    ) -> List[Tuple[str, float]]:
        """
        Use BERT's masked language modeling to find important words.
        This method masks words and sees which ones BERT finds most important to predict.
        """
        # Load masked LM model if not already loaded
        if not hasattr(self, "mlm_model"):
            self.mlm_model = AutoModelForMaskedLM.from_pretrained(self.model_name).to(
                self.device
            )
            self.mlm_model.eval()

        # Tokenize text
        tokens = self.tokenizer.tokenize(text)
        if len(tokens) > 500:  # Limit for efficiency
            tokens = tokens[:500]

        important_words = []

        # Try masking each significant token
        for i, token in enumerate(tokens):
            if token.startswith("##") or token in ["[CLS]", "[SEP]", "[PAD]"]:
                continue

            # Create masked version
            masked_tokens = tokens.copy()
            masked_tokens[i] = "[MASK]"

            # Convert to input format
            input_text = self.tokenizer.convert_tokens_to_string(masked_tokens)
            inputs = self.tokenizer(input_text, return_tensors="pt").to(self.device)

            with torch.no_grad():
                outputs = self.mlm_model(**inputs)
                predictions = outputs.logits

                # Get the predicted token for the masked position
                mask_token_index = (inputs.input_ids == self.tokenizer.mask_token_id)[
                    0
                ].nonzero(as_tuple=True)[0]
                if len(mask_token_index) > 0:
                    mask_token_logits = predictions[0, mask_token_index[0], :]

                    # Calculate probability of original token
                    original_token_id = self.tokenizer.convert_tokens_to_ids([token])[0]
                    original_prob = torch.softmax(mask_token_logits, dim=-1)[
                        original_token_id
                    ].item()

                    if len(token) > 2 and not token.startswith("#"):
                        important_words.append((token, original_prob))

        # Sort by importance and return top_k
        important_words.sort(key=lambda x: x[1], reverse=True)
        return important_words[:top_k]

    def semantic_keyword_clustering(
        self, documents: List[str], n_clusters: int = 5
    ) -> Dict:
        """
        Cluster documents and extract representative keywords for each cluster.
        """
        # Get document embeddings
        doc_embeddings = self.get_bert_embeddings(documents)

        # Perform clustering
        kmeans = KMeans(n_clusters=min(n_clusters, len(documents)), random_state=42)
        cluster_labels = kmeans.fit_predict(doc_embeddings)

        # Extract keywords for each cluster
        cluster_keywords = defaultdict(list)

        for doc_idx, cluster_id in enumerate(cluster_labels):
            # Extract keywords from each document in the cluster
            keywords = self.bert_keyword_extraction(documents[doc_idx])
            cluster_keywords[cluster_id].extend([kw[0] for kw in keywords])

        # Get most common keywords per cluster
        cluster_results = {}
        for cluster_id, keywords in cluster_keywords.items():
            keyword_counts = Counter(keywords)
            cluster_results[cluster_id] = {
                "top_keywords": keyword_counts.most_common(10),
                "document_count": sum(
                    1 for label in cluster_labels if label == cluster_id
                ),
                "documents": [
                    i for i, label in enumerate(cluster_labels) if label == cluster_id
                ],
            }

        return {
            "clusters": cluster_results,
            "cluster_labels": cluster_labels.tolist(),
            "cluster_centers": kmeans.cluster_centers_,
        }

    def analyze_documents_with_bert(
        self, documents: List[str], use_clustering: bool = True, use_mlm: bool = False
    ) -> Dict:
        """
        Main analysis method with periodic checkpointing.
        """
        results = {
            "document_keywords": [],
            "document_languages": [],
            "global_analysis": {},
            "clusters": None,
        }

        # <<< ADD THIS: Define checkpoint settings >>>
        save_interval = 100  # Save results every 100 documents
        checkpoint_file = "bert_analysis_checkpoint.xlsx"

        print(f"Analyzing {len(documents)} documents with BERT...")

        # Analyze each document
        for i, doc in enumerate(documents):
            print(f"Processing document {i+1}/{len(documents)}")

            # --- (Your existing logic for handling empty docs, langdetect, etc.) ---
            if not doc or doc.isspace():
                # ... (omitted for brevity)
                continue

            try:
                lang = detect(doc)
            except:
                lang = "unknown"

            results["document_languages"].append(lang)
            bert_keywords = self.bert_keyword_extraction(doc)
            doc_result = {
                "document_id": i,
                "language": lang,
                "bert_keywords": bert_keywords,
            }

            if use_mlm:
                # ... (omitted for brevity)
                pass

            results["document_keywords"].append(doc_result)

            # <<< ADD THIS BLOCK FOR PERIODIC SAVING >>>
            # Check if it's time to save a checkpoint
            if (i + 1) % save_interval == 0 and i < len(documents) - 1:
                print(
                    f"\n--- Saving checkpoint at document {i+1} to {checkpoint_file} ---\n"
                )

                # Recalculate global analysis on the partial results before saving
                temp_all_keywords = [
                    kw[0]
                    for res in results["document_keywords"]
                    for kw in res["bert_keywords"]
                ]
                results["global_analysis"] = {
                    "top_global_keywords": Counter(temp_all_keywords).most_common(20),
                    "language_distribution": Counter(results["document_languages"]),
                    "total_unique_keywords": len(set(temp_all_keywords)),
                }

                # Save the current state
                self.save_bert_results(results, output_file=checkpoint_file)

        # --- (Your existing code for final clustering and global analysis) ---
        # This part runs once at the very end to give you the complete, final result.
        print("Performing final analysis...")

        # Semantic clustering analysis
        if use_clustering and len(documents) > 2:
            print("Performing semantic clustering...")
            cluster_results = self.semantic_keyword_clustering(documents)
            results["clusters"] = cluster_results

        # Global keyword analysis
        all_keywords = []
        for doc_result in results["document_keywords"]:
            all_keywords.extend([kw[0] for kw in doc_result["bert_keywords"]])

        global_keyword_counts = Counter(all_keywords)
        results["global_analysis"] = {
            "top_global_keywords": global_keyword_counts.most_common(20),
            "language_distribution": Counter(results["document_languages"]),
            "total_unique_keywords": len(set(all_keywords)),
        }

        return results

    def save_bert_results(
        self, results: Dict, output_file: str = "bert_keyword_analysis.xlsx"
    ):
        """Save BERT analysis results to Excel with proper cleaning."""

        with pd.ExcelWriter(output_file, engine="openpyxl") as writer:

            # --- Sheet 1: Summary ---
            if results.get("global_analysis"):
                summary_data = {
                    "Language Distribution": [
                        str(dict(results["global_analysis"]["language_distribution"]))
                    ],
                    "Total Unique Keywords": [
                        results["global_analysis"]["total_unique_keywords"]
                    ],
                }
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name="Summary", index=False)

            # --- Sheet 2: Document-Level Keywords ---
            doc_data = []
            for doc_result in results["document_keywords"]:
                # <<< CLEANED >>> Applied clean_text_for_excel to keywords
                cleaned_keywords_str = ", ".join(
                    [
                        clean_text_for_excel(kw[0])
                        for kw in doc_result["bert_keywords"][:10]
                    ]
                )
                cleaned_scores_str = ", ".join(
                    [
                        f"{clean_text_for_excel(kw[0])}({kw[1]:.3f})"
                        for kw in doc_result["bert_keywords"][:5]
                    ]
                )
                doc_data.append(
                    {
                        "Document_ID": doc_result["document_id"],
                        "Language": doc_result["language"],
                        "Top_BERT_Keywords": cleaned_keywords_str,
                        "Keyword_Scores": cleaned_scores_str,
                    }
                )
            doc_df = pd.DataFrame(doc_data)
            doc_df.to_excel(writer, sheet_name="Document Keywords", index=False)

            # --- Sheet 3: Top Global Keywords ---
            if results.get("global_analysis"):
                # <<< CLEANED >>> Applied clean_text_for_excel to global keywords
                cleaned_global_keywords = [
                    (clean_text_for_excel(kw), freq)
                    for kw, freq in results["global_analysis"]["top_global_keywords"]
                ]
                global_df = pd.DataFrame(
                    cleaned_global_keywords, columns=["Keyword", "Frequency"]
                )
                global_df.to_excel(writer, sheet_name="Global Keywords", index=False)

            # --- Sheet 4: Semantic Clusters ---
            if results["clusters"]:
                cluster_data = []
                for cluster_id, cluster_info in results["clusters"]["clusters"].items():
                    # <<< CLEANED >>> Applied clean_text_for_excel to cluster keywords
                    cleaned_cluster_keywords = ", ".join(
                        [
                            clean_text_for_excel(kw[0])
                            for kw in cluster_info["top_keywords"][:10]
                        ]
                    )
                    cluster_data.append(
                        {
                            "Cluster_ID": cluster_id,
                            "Document_Count": cluster_info["document_count"],
                            "Top_Keywords": cleaned_cluster_keywords,
                            "Documents": ", ".join(map(str, cluster_info["documents"])),
                        }
                    )
                cluster_df = pd.DataFrame(cluster_data)
                cluster_df.to_excel(writer, sheet_name="Semantic Clusters", index=False)

        print(f"BERT analysis results saved to {output_file}")


def main():
    """Example usage optimized for CPU processing."""

    with open("traffic_urls_with_text.csv", "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        text = [row[32] for row in reader]

    samples = text[1:]
    # Initialize CPU-optimized analyzer
    print("Initializing CPU-optimized BERT analyzer...")
    analyzer = BERTKeywordAnalyzer("distilbert-base-multilingual-cased")

    # Analyze documents
    print(f"\nAnalyzing {len(samples)} documents...")
    results = analyzer.analyze_documents_with_bert(
        samples,
        use_clustering=True,
        use_mlm=False,  # Set to True for masked language modeling (slower)
    )

    print("\n=== BERT KEYWORD ANALYSIS RESULTS ===")
    print(f"Languages detected: {results['global_analysis']['language_distribution']}")
    print(
        f"Top global keywords: {[kw[0] for kw in results['global_analysis']['top_global_keywords'][:10]]}"
    )

    if results["clusters"]:
        print(f"Number of semantic clusters: {len(results['clusters']['clusters'])}")

    # Save results
    analyzer.save_bert_results(results, "bert_keyword_1.xlsx")

    return results


if __name__ == "__main__":
    results = main()
