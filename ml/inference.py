"""
Xiphos Helios Adverse Media Classifier - Inference Module

Loads the fine-tuned DistilBERT model and classifies OSINT findings
as adverse or non-adverse with a confidence score.

This module is imported by the Google News and GDELT connectors
to replace keyword-based adverse detection.

Usage:
    from ml.inference import classify_finding, is_model_available

    if is_model_available():
        result = classify_finding("Company indicted on fraud charges")
        # result = {"adverse": True, "confidence": 0.94, "method": "ml"}
    else:
        # Fall back to keyword matching
        ...
"""

import os
import json
from typing import Optional

# Lazy-load torch/transformers to avoid import overhead when model isn't available
_model = None
_tokenizer = None
_device = None
_available: Optional[bool] = None

MODEL_DIR = os.environ.get("XIPHOS_ML_MODEL_DIR", "/app/ml/model")
CONFIDENCE_THRESHOLD = 0.65  # Below this, fall back to keyword matching


def is_model_available() -> bool:
    """Check if the ML model is available (without loading it)."""
    global _available
    if _available is not None:
        return _available
    _available = os.path.exists(os.path.join(MODEL_DIR, "config.json"))
    return _available


def _load_model():
    """Lazy-load the model on first inference call."""
    global _model, _tokenizer, _device

    if _model is not None:
        return

    import torch
    from transformers import DistilBertTokenizer, DistilBertForSequenceClassification

    # Device selection: MPS > CUDA > CPU
    if torch.backends.mps.is_available():
        _device = torch.device("mps")
    elif torch.cuda.is_available():
        _device = torch.device("cuda")
    else:
        _device = torch.device("cpu")

    _tokenizer = DistilBertTokenizer.from_pretrained(MODEL_DIR)
    _model = DistilBertForSequenceClassification.from_pretrained(MODEL_DIR)
    _model.to(_device)
    _model.eval()


def classify_finding(text: str) -> dict:
    """
    Classify a single OSINT finding as adverse or non-adverse.

    Args:
        text: The finding text (title + detail)

    Returns:
        {
            "adverse": bool,      # True if classified as adverse
            "confidence": float,  # 0.0-1.0 confidence in the prediction
            "method": "ml",       # Always "ml" for this classifier
            "label": str,         # "ADVERSE" or "NOT_ADVERSE"
        }
    """
    if not is_model_available():
        return {"adverse": False, "confidence": 0.0, "method": "unavailable", "label": "UNKNOWN"}

    _load_model()

    import torch

    # Tokenize
    inputs = _tokenizer(
        text[:512], truncation=True, padding=True,
        max_length=128, return_tensors="pt"
    )
    inputs = {k: v.to(_device) for k, v in inputs.items()}

    # Inference
    with torch.no_grad():
        outputs = _model(**inputs)
        probs = torch.softmax(outputs.logits, dim=-1)
        pred_class = torch.argmax(probs, dim=-1).item()
        confidence = probs[0][pred_class].item()

    is_adverse = pred_class == 1
    label = "ADVERSE" if is_adverse else "NOT_ADVERSE"

    return {
        "adverse": is_adverse,
        "confidence": round(confidence, 4),
        "method": "ml",
        "label": label,
    }


def classify_batch(texts: list[str]) -> list[dict]:
    """
    Classify a batch of findings efficiently.

    Args:
        texts: List of finding texts

    Returns:
        List of classification results (same format as classify_finding)
    """
    if not is_model_available() or not texts:
        return [{"adverse": False, "confidence": 0.0, "method": "unavailable", "label": "UNKNOWN"}] * len(texts)

    _load_model()

    import torch

    # Batch tokenize
    inputs = _tokenizer(
        [t[:512] for t in texts], truncation=True, padding=True,
        max_length=128, return_tensors="pt"
    )
    inputs = {k: v.to(_device) for k, v in inputs.items()}

    # Batch inference
    with torch.no_grad():
        outputs = _model(**inputs)
        probs = torch.softmax(outputs.logits, dim=-1)
        pred_classes = torch.argmax(probs, dim=-1)

    results = []
    for i in range(len(texts)):
        pred = pred_classes[i].item()
        conf = probs[i][pred].item()
        results.append({
            "adverse": pred == 1,
            "confidence": round(conf, 4),
            "method": "ml",
            "label": "ADVERSE" if pred == 1 else "NOT_ADVERSE",
        })

    return results


def get_model_info() -> dict:
    """Get model metadata (training info, size, etc.)."""
    meta_path = os.path.join(MODEL_DIR, "training_meta.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            return json.load(f)
    return {"status": "no_model" if not is_model_available() else "no_metadata"}
