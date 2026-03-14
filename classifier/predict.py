"""
predict.py — Étapes 3+4: Inférence + Supabase cache

Classifie les produits en utilisant le classifier entrainé.
Si confidence < seuil, fallback vers LLM.
Cache tous les résultats dans Supabase product_classifications.

Usage:
    from classifier.predict import classify_products

    products = [
        {"name": "iPhone 15", "brand": "Apple", "description": "..."},
        ...
    ]

    results = classify_products(products, confidence_threshold=0.7)

    for p in results:
        print(f"{p['name']} → {p['ml_niche_predicted']} ({p['ml_confidence_score']})")
"""

import logging
from typing import Any, Optional

import numpy as np

from classifier.utils import (
    batch_embed,
    build_embedding_text,
    load_classifier,
    md5_hash,
    sb_check_cache,
    sb_save_classification,
)
from settings import CLASSIFICATION_LLM, LLM_BACKEND, GOOGLE_AI_API_KEY, OLLAMA_CLOUD_API_KEY

logger = logging.getLogger(__name__)


def classify_products(
    products: list[dict],
    confidence_threshold: float = 0.7,
    use_llm_fallback: bool = True,
    batch_size: int = 100,
) -> list[dict]:
    """
    Classify products using trained sklearn classifier + LLM fallback.

    Args:
        products: List of product dicts (must have: name, brand, description, id)
        confidence_threshold: Min confidence for sklearn result (0.0-1.0)
        use_llm_fallback: If True, use LLM for low-confidence predictions
        batch_size: Number of products to process per batch

    Returns:
        List of enriched products with:
          - ml_niche_predicted: Predicted niche string
          - ml_confidence_score: Confidence float (0.0-1.0)
          - ml_source: "sklearn" or "llm"
    """
    if not products:
        return []

    logger.info(f"Predicting on {len(products)} products (threshold={confidence_threshold})")

    # Load classifier
    try:
        classifier, label_encoder = load_classifier()
    except FileNotFoundError as e:
        logger.error(f"Classifier not found: {e}")
        raise

    results = []

    # Process in batches
    for batch_idx in range(0, len(products), batch_size):
        batch = products[batch_idx : batch_idx + batch_size]

        logger.info(f"Processing batch {batch_idx // batch_size + 1} ({len(batch)} products)")

        # Check cache for each product
        cached_products = []
        uncached_products = []

        for product in batch:
            product_hash = md5_hash(product.get("name", ""), product.get("brand", ""))

            cached = sb_check_cache(product_hash)

            if cached:
                # Enrich from cache
                enriched = {**product, **cached}
                enriched["ml_niche_predicted"] = cached["niche"]
                enriched["ml_confidence_score"] = cached["confidence"]
                enriched["ml_source"] = cached["source"]
                cached_products.append(enriched)
                logger.debug(f"Cache hit: {product.get('name')} → {cached['niche']}")
            else:
                uncached_products.append(product)

        # Classify uncached products
        if uncached_products:
            classified = _classify_batch(
                uncached_products,
                classifier,
                label_encoder,
                confidence_threshold,
                use_llm_fallback,
            )

            results.extend(classified)

        # Add cached products
        results.extend(cached_products)

    logger.info(f"✓ Classified {len(results)} products")

    return results


def _classify_batch(
    products: list[dict],
    classifier: Any,
    label_encoder: Any,
    confidence_threshold: float,
    use_llm_fallback: bool,
) -> list[dict]:
    """
    Internal: Classify a batch of uncached products.

    Returns: List of enriched products
    """
    # Generate embeddings
    embedding_texts = [build_embedding_text(p.get("name"), p.get("brand"), p.get("description")) for p in products]

    embeddings = batch_embed(embedding_texts)

    # Predict with classifier
    predictions = classifier.predict(embeddings)
    probabilities = classifier.predict_proba(embeddings)

    # Get class labels and max probabilities
    class_indices = np.argmax(probabilities, axis=1)
    max_probabilities = np.max(probabilities, axis=1)

    results = []

    for i, product in enumerate(products):
        predicted_class_idx = class_indices[i]
        predicted_niche = label_encoder.classes_[predicted_class_idx]
        confidence = float(max_probabilities[i])

        product_hash = md5_hash(product.get("name", ""), product.get("brand", ""))

        # Decide: use sklearn or fallback to LLM
        if confidence >= confidence_threshold:
            # Use sklearn result
            enriched = {
                **product,
                "ml_niche_predicted": predicted_niche,
                "ml_confidence_score": confidence,
                "ml_source": "sklearn",
            }

            # Save to cache (optional)
            if product.get("id"):
                sb_save_classification(
                    product["id"],
                    product_hash,
                    predicted_niche,
                    confidence,
                    "sklearn",
                )

            results.append(enriched)
            logger.debug(f"sklearn: {product.get('name')} → {predicted_niche} ({confidence:.2f})")

        elif use_llm_fallback:
            # Use LLM fallback
            llm_result = _classify_with_llm(product, products.index(product), len(products))

            if llm_result:
                combined = {**product, **llm_result}

                # Save to cache
                if product.get("id"):
                    sb_save_classification(
                        product["id"],
                        product_hash,
                        llm_result["ml_niche_predicted"],
                        llm_result["ml_confidence_score"],
                        "llm",
                    )

                results.append(combined)
                logger.debug(f"llm: {product.get('name')} → {llm_result['ml_niche_predicted']}")
            else:
                # LLM failed, use sklearn result anyway
                enriched = {
                    **product,
                    "ml_niche_predicted": predicted_niche,
                    "ml_confidence_score": confidence,
                    "ml_source": "sklearn",
                }
                results.append(enriched)
                logger.warning(f"LLM fallback failed, using sklearn: {product.get('name')}")

        else:
            # No fallback, use sklearn even if low confidence
            enriched = {
                **product,
                "ml_niche_predicted": predicted_niche,
                "ml_confidence_score": confidence,
                "ml_source": "sklearn",
            }
            results.append(enriched)

    return results


def _classify_with_llm(
    product: dict,
    batch_idx: int,
    batch_total: int,
) -> Optional[dict]:
    """
    Fallback: Classify a single product using LLM.

    Returns:
        Dict with {ml_niche_predicted, ml_confidence_score} or None
    """
    try:
        # Build prompt
        name = product.get("name", "")
        brand = product.get("brand", "")
        description = product.get("description", "")[:300]

        prompt = f"""Classify this product into ONE niche category.

Product:
- Name: {name}
- Brand: {brand}
- Description: {description}

Return ONLY the niche category name (short word, lowercase, e.g., "gaming" or "office-setup").
"""

        # Call LLM
        if LLM_BACKEND == "gemini" and GOOGLE_AI_API_KEY:
            result = _call_gemini(prompt)
        else:
            result = _call_ollama(prompt)

        if result:
            return {
                "ml_niche_predicted": result.strip().lower(),
                "ml_confidence_score": 0.95,  # Approximation for LLM
            }

        return None

    except Exception as e:
        logger.error(f"LLM classification failed: {e}")
        return None


def _call_gemini(prompt: str) -> Optional[str]:
    """Call Gemini API for classification."""
    import google.generativeai as genai

    try:
        genai.configure(api_key=google.GOOGLE_AI_API_KEY)
        model = genai.GenerativeModel(CLASSIFICATION_LLM)
        response = model.generate_content(prompt, temperature=0.3)
        return response.text if response else None
    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        return None


def _call_ollama(prompt: str) -> Optional[str]:
    """Call Ollama Cloud API for classification."""
    import requests

    try:
        # Ollama Cloud endpoint (assuming same as classification.py)
        url = "https://ollama.cloud/api/generate"  # Adjust based on your setup

        payload = {
            "model": CLASSIFICATION_LLM,
            "prompt": prompt,
            "stream": False,
            "temperature": 0.3,
        }

        headers = {"Authorization": f"Bearer {OLLAMA_CLOUD_API_KEY}"} if OLLAMA_CLOUD_API_KEY else {}

        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        return data.get("response", "").strip() if "response" in data else None

    except Exception as e:
        logger.error(f"Ollama call failed: {e}")
        return None


# CLI interface
if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Classify products")
    parser.add_argument("--json", help="Path to JSON file with products list")
    parser.add_argument("--threshold", type=float, default=0.7, help="Confidence threshold")
    parser.add_argument("--no-llm-fallback", action="store_true", help="Disable LLM fallback")

    args = parser.parse_args()

    if args.json:
        with open(args.json) as f:
            products = json.load(f)

        results = classify_products(
            products,
            confidence_threshold=args.threshold,
            use_llm_fallback=not args.no_llm_fallback,
        )

        print(json.dumps(results, indent=2))
    else:
        print("Usage: python -m classifier.predict --json products.json")
        sys.exit(1)
