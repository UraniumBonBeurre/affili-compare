"""
Utility functions for classifier module.
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional, Tuple

import joblib
import numpy as np
import requests
from sentence_transformers import SentenceTransformer

from settings import SUPABASE_KEY, SUPABASE_URL, sb_headers

logger = logging.getLogger(__name__)

# Lazy-loaded models
_EMBEDDER_CACHE: Optional[SentenceTransformer] = None
_CLASSIFIER_CACHE: Optional[Any] = None
_LABEL_ENCODER_CACHE: Optional[Any] = None

CLASSIFIER_DIR = Path(__file__).parent


def get_classifier_dir() -> Path:
    """Get classifier directory, create if needed."""
    return CLASSIFIER_DIR


def md5_hash(name: str, brand: str) -> str:
    """
    Generate MD5 hash from product name + brand.
    Used as cache key for product_classifications.

    Args:
        name: Product name
        brand: Product brand

    Returns:
        32-char MD5 hash string
    """
    text = f"{name.lower().strip()}_{brand.lower().strip()}"
    return hashlib.md5(text.encode()).hexdigest()


def truncate_text(text: Optional[str], max_len: int = 500) -> str:
    """
    Truncate and clean text for embedding.

    Args:
        text: Input text (may be None)
        max_len: Maximum length

    Returns:
        Cleaned, truncated string
    """
    if not text:
        return ""

    # Remove extra whitespace, newlines
    cleaned = " ".join(text.split())

    # Truncate
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]

    return cleaned


def load_embedder() -> SentenceTransformer:
    """
    Lazy-load sentence-transformers model for embeddings.
    Model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

    Returns:
        SentenceTransformer instance
    """
    global _EMBEDDER_CACHE

    if _EMBEDDER_CACHE is None:
        logger.info("Loading embedder model: paraphrase-multilingual-MiniLM-L12-v2")
        _EMBEDDER_CACHE = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

    return _EMBEDDER_CACHE


def batch_embed(texts: list[str], batch_size: int = 512) -> np.ndarray:
    """
    Generate embeddings for a batch of texts.

    Args:
        texts: List of texts to embed
        batch_size: Batch size for embedding (avoid OOM)

    Returns:
        numpy array of shape (len(texts), 384)
    """
    embedder = load_embedder()

    logger.debug(f"Embedding {len(texts)} texts in batches of {batch_size}")
    embeddings = embedder.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=len(texts) > 100,
        convert_to_numpy=True,
    )

    return embeddings


def load_classifier() -> Tuple[Any, Any]:
    """
    Lazy-load trained classifier and label encoder.

    Returns:
        (classifier, label_encoder) tuple

    Raises:
        FileNotFoundError: If model files don't exist
    """
    global _CLASSIFIER_CACHE, _LABEL_ENCODER_CACHE

    classifier_path = get_classifier_dir() / "classifier.pkl"
    encoder_path = get_classifier_dir() / "label_encoder.pkl"

    if not classifier_path.exists() or not encoder_path.exists():
        raise FileNotFoundError(
            f"Classifier not found. Train first:\n"
            f"  python3 -m classifier.train\n"
            f"Expected: {classifier_path}, {encoder_path}"
        )

    if _CLASSIFIER_CACHE is None:
        logger.info("Loading classifier and label encoder")
        _CLASSIFIER_CACHE = joblib.load(classifier_path)
        _LABEL_ENCODER_CACHE = joblib.load(encoder_path)

    return _CLASSIFIER_CACHE, _LABEL_ENCODER_CACHE


def sb_check_cache(product_hash: str) -> Optional[dict]:
    """
    Query Supabase product_classifications table for cached result.

    Args:
        product_hash: MD5 hash of name+brand

    Returns:
        Dict with {predicted_niche, confidence_score, source} or None if not found
    """
    try:
        url = f"{SUPABASE_URL}/rest/v1/product_classifications?product_hash=eq.{product_hash}&limit=1"
        resp = requests.get(url, headers=sb_headers(), timeout=5)
        resp.raise_for_status()

        data = resp.json()
        if data and len(data) > 0:
            row = data[0]
            return {
                "niche": row.get("predicted_niche"),
                "confidence": float(row.get("confidence_score", 0)),
                "source": row.get("source"),
            }

        return None
    except Exception as e:
        logger.warning(f"Cache lookup failed for {product_hash}: {e}")
        return None


def sb_save_classification(
    product_id: str,
    product_hash: str,
    predicted_niche: str,
    confidence_score: float,
    source: str,
    model_version: str = "v1.0",
) -> bool:
    """
    Save classification result to Supabase product_classifications table.

    Args:
        product_id: UUID of product
        product_hash: MD5 hash of name+brand
        predicted_niche: Predicted niche/category
        confidence_score: Confidence (0.0-1.0)
        source: "sklearn" or "llm"
        model_version: Model version string

    Returns:
        True if saved, False otherwise
    """
    try:
        payload = {
            "product_id": product_id,
            "product_hash": product_hash,
            "predicted_niche": predicted_niche,
            "confidence_score": float(confidence_score),
            "source": source,
            "model_version": model_version,
        }

        url = f"{SUPABASE_URL}/rest/v1/product_classifications"
        resp = requests.post(
            url,
            headers=sb_headers({"Prefer": "resolution=ignore-duplicates"}),
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()

        return True
    except Exception as e:
        logger.warning(f"Cache save failed: {e}")
        return False


def build_embedding_text(name: str, brand: str, description: str) -> str:
    """
    Build text for embedding from product fields.

    Args:
        name: Product name
        brand: Product brand
        description: Product description

    Returns:
        Combined text for embedding
    """
    parts = []

    if brand and brand.strip():
        parts.append(truncate_text(brand, 100))

    if name and name.strip():
        parts.append(truncate_text(name, 200))

    if description and description.strip():
        parts.append(truncate_text(description, 200))

    return " ".join(parts)


def retry_with_backoff(max_retries: int = 3):
    """
    Decorator for retry logic with exponential backoff.
    """
    import time
    from functools import wraps

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries:
                        raise
                    wait_time = 2 ** (attempt - 1)
                    logger.warning(f"Attempt {attempt}/{max_retries} failed, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)

        return wrapper

    return decorator
