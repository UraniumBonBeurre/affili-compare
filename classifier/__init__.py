"""
Classifier module for product classification using sklearn + sentence-transformers.

Workflow:
1. train.py → Entraîner sur labeled_products.csv (embeddings + LogisticRegression)
2. predict.py → Inférence batch sur nouveaux produits (avec fallback LLM)

Usage:
    python3 -m classifier.train       # Entraîner le classifier
    python3 -m classifier.predict     # Inférence batch

Environment:
    CLASSIFIER_MODEL_DIR: Répertoire pour sauvegarder les modèles (default: ./classifier/)
"""

__version__ = "1.0.0"
