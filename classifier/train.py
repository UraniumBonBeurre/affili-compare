"""
train.py — Étapes 1+2: Entraînement du classifieur

Input: labeled_products.csv (colonnes: name, brand, description, niche)
Output:
  - embeddings.npy
  - labels.npy
  - classifier.pkl
  - label_encoder.pkl
  - classification_report (console)

Usage:
    python3 -m classifier.train [--csv labeled_products.csv] [--test-split 0.2]
"""

import argparse
import csv
import logging
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

from classifier.utils import batch_embed, build_embedding_text, get_classifier_dir

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def load_labeled_csv(csv_path: str) -> tuple[list[dict], list[str]]:
    """
    Load labeled products from CSV.

    Expected columns: name, brand, description, niche

    Args:
        csv_path: Path to CSV file

    Returns:
        (list of product dicts, list of niches)
    """
    products = []
    niches_set = set()

    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    logger.info(f"Loading {csv_path}")

    with open(csv_file, encoding="utf-8") as f:
        reader = csv.DictReader(f)

        if not reader.fieldnames or "name" not in reader.fieldnames:
            raise ValueError(f"CSV must have 'name' column. Found: {reader.fieldnames}")

        for i, row in enumerate(reader):
            # Validate required columns
            name = row.get("name", "").strip()
            brand = row.get("brand", "").strip()
            description = row.get("description", "").strip()
            niche = row.get("niche", "").strip()

            if not name:
                logger.warning(f"Row {i} has empty name, skipping")
                continue

            if not niche:
                logger.warning(f"Row {i} ({name}) has empty niche, skipping")
                continue

            products.append(
                {
                    "name": name,
                    "brand": brand,
                    "description": description,
                    "niche": niche,
                    "embedding_text": build_embedding_text(name, brand, description),
                }
            )

            niches_set.add(niche)

    if not products:
        raise ValueError(f"No valid products loaded from {csv_path}")

    niches = sorted(list(niches_set))

    logger.info(f"Loaded {len(products)} products across {len(niches)} niches")
    logger.info(f"Niches: {', '.join(niches)}")

    return products, niches


def generate_embeddings(products: list[dict], batch_size: int = 512) -> np.ndarray:
    """
    Generate embeddings for all products.

    Args:
        products: List of product dicts (with 'embedding_text' key)
        batch_size: Batch size for embedding

    Returns:
        numpy array of shape (len(products), 384)
    """
    texts = [p["embedding_text"] for p in products]

    logger.info(f"Generating embeddings for {len(texts)} products (batch_size={batch_size})")

    embeddings = batch_embed(texts, batch_size=batch_size)

    logger.info(f"Embeddings shape: {embeddings.shape}")

    return embeddings


def train_classifier(
    embeddings: np.ndarray,
    labels: list[str],
    max_iter: int = 1000,
    C: float = 5,
    test_split: float = 0.2,
) -> tuple[LogisticRegression, LabelEncoder, dict]:
    """
    Train LogisticRegression classifier on embeddings.

    Args:
        embeddings: Feature matrix (n_samples, n_features)
        labels: List of labels (niches)
        max_iter: Max iterations for LR
        C: Regularization parameter (inverse of regularization strength)
        test_split: Train/test split ratio

    Returns:
        (trained_classifier, label_encoder, metrics_dict)
    """
    logger.info(f"Training classifier with max_iter={max_iter}, C={C}")

    # Encode labels
    le = LabelEncoder()
    y = le.fit_transform(labels)

    logger.info(f"Label classes: {le.classes_}")

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        embeddings, y, test_size=test_split, random_state=42, stratify=y
    )

    logger.info(f"Train set: {len(X_train)} samples, Test set: {len(X_test)} samples")

    # Train classifier
    clf = LogisticRegression(max_iter=max_iter, C=C, solver="lbfgs", n_jobs=-1, random_state=42)

    logger.info("Fitting LogisticRegression...")

    clf.fit(X_train, y_train)

    # Evaluate
    y_pred = clf.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)

    logger.info(f"Test Accuracy: {accuracy:.4f}")

    # Classification report
    report = classification_report(y_test, y_pred, target_names=le.classes_)

    logger.info("\nClassification Report:\n" + report)

    # Confusion matrix
    cm = confusion_matrix(y_test, y_pred)
    logger.info(f"Confusion Matrix:\n{cm}")

    metrics = {
        "accuracy": float(accuracy),
        "test_samples": len(X_test),
        "train_samples": len(X_train),
        "n_classes": len(le.classes_),
        "test_split": test_split,
    }

    return clf, le, metrics


def save_models(
    classifier: LogisticRegression,
    label_encoder: LabelEncoder,
    embeddings: np.ndarray,
    labels_encoded: np.ndarray,
) -> None:
    """
    Save trained classifier, label encoder, and embeddings to disk.

    Args:
        classifier: Trained LogisticRegression
        label_encoder: Fitted LabelEncoder
        embeddings: Embedding matrix
        labels_encoded: Encoded labels
    """
    import joblib

    classifier_dir = get_classifier_dir()
    classifier_dir.mkdir(exist_ok=True)

    # Save models
    classifier_path = classifier_dir / "classifier.pkl"
    encoder_path = classifier_dir / "label_encoder.pkl"
    embeddings_path = classifier_dir / "embeddings.npy"
    labels_path = classifier_dir / "labels.npy"

    logger.info(f"Saving classifier to {classifier_path}")
    joblib.dump(classifier, classifier_path)

    logger.info(f"Saving label encoder to {encoder_path}")
    joblib.dump(label_encoder, encoder_path)

    logger.info(f"Saving embeddings to {embeddings_path}")
    np.save(embeddings_path, embeddings)

    logger.info(f"Saving labels to {labels_path}")
    np.save(labels_path, labels_encoded)

    logger.info("✓ All models saved successfully")


def main():
    parser = argparse.ArgumentParser(
        description="Train classifier on labeled products",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 -m classifier.train
  python3 -m classifier.train --csv my_data.csv --test-split 0.25
        """,
    )

    parser.add_argument(
        "--csv",
        default="labeled_products.csv",
        help="Path to labeled products CSV (default: labeled_products.csv)",
    )

    parser.add_argument(
        "--test-split",
        type=float,
        default=0.2,
        help="Train/test split ratio (default: 0.2)",
    )

    parser.add_argument(
        "--max-iter",
        type=int,
        default=1000,
        help="Max iterations for LogisticRegression (default: 1000)",
    )

    parser.add_argument(
        "--c",
        type=float,
        default=5,
        help="Regularization parameter C (default: 5)",
    )

    args = parser.parse_args()

    try:
        # Load CSV
        products, niches = load_labeled_csv(args.csv)

        # Generate embeddings
        embeddings = generate_embeddings(products)

        # Prepare labels
        labels = [p["niche"] for p in products]

        # Train classifier
        classifier, le, metrics = train_classifier(
            embeddings,
            labels,
            max_iter=args.max_iter,
            C=args.c,
            test_split=args.test_split,
        )

        # Encode all labels for storage
        labels_encoded = le.transform(labels)

        # Save models
        save_models(classifier, le, embeddings, labels_encoded)

        logger.info("✓ Training complete!")
        logger.info(f"Metrics: {metrics}")

    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
