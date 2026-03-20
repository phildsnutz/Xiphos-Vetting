#!/usr/bin/env python3
"""
Xiphos Helios Adverse Media Classifier - Training Script

Fine-tunes DistilBERT for binary classification:
  Is this OSINT finding genuinely adverse for a defense contractor?

Optimized for Apple Silicon M2 Max (MPS acceleration).
Falls back to CUDA if available, then CPU.

Prerequisites:
  pip install torch transformers datasets scikit-learn

Usage:
  python3 ml/train_classifier.py                    # Train from exported data
  python3 ml/train_classifier.py --epochs 5         # Custom epochs
  python3 ml/train_classifier.py --data my_data.csv # Custom data file

Output:
  ml/model/  - Saved model + tokenizer (drop into Docker image)
"""

import argparse
import os
import sys
import csv
import json
from pathlib import Path

import torch
from torch.utils.data import Dataset, DataLoader
from transformers import (
    DistilBertTokenizer,
    DistilBertForSequenceClassification,
    get_linear_schedule_with_warmup,
)
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix


# ---- Config ----
DEFAULT_DATA = "ml/training_data.csv"
MODEL_NAME = "distilbert-base-uncased"
OUTPUT_DIR = "ml/model"
MAX_LENGTH = 128
BATCH_SIZE = 16
LEARNING_RATE = 2e-5
WEIGHT_DECAY = 0.01


def get_device():
    """Detect best available device: MPS (Apple Silicon) > CUDA > CPU."""
    if torch.backends.mps.is_available():
        print("Using Apple Silicon MPS acceleration")
        return torch.device("mps")
    elif torch.cuda.is_available():
        print(f"Using CUDA: {torch.cuda.get_device_name(0)}")
        return torch.device("cuda")
    else:
        print("Using CPU (training will be slower)")
        return torch.device("cpu")


class FindingsDataset(Dataset):
    """PyTorch dataset for OSINT findings."""

    def __init__(self, texts, labels, tokenizer, max_length=MAX_LENGTH):
        self.encodings = tokenizer(
            texts, truncation=True, padding=True,
            max_length=max_length, return_tensors="pt"
        )
        self.labels = torch.tensor(labels, dtype=torch.long)

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        return {
            "input_ids": self.encodings["input_ids"][idx],
            "attention_mask": self.encodings["attention_mask"][idx],
            "labels": self.labels[idx],
        }


def load_data(data_path: str):
    """Load and split training data from CSV."""
    texts, labels = [], []
    with open(data_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            text = row.get('text', '')
            label = int(row.get('label', 0))
            if text.strip():
                texts.append(text[:512])  # Truncate long texts
                labels.append(label)

    print(f"Loaded {len(texts)} examples ({sum(labels)} adverse, {len(labels)-sum(labels)} non-adverse)")

    # Stratified split
    train_texts, val_texts, train_labels, val_labels = train_test_split(
        texts, labels, test_size=0.15, random_state=42, stratify=labels
    )
    print(f"Train: {len(train_texts)}, Validation: {len(val_texts)}")
    return train_texts, val_texts, train_labels, val_labels


def train(args):
    device = get_device()

    # Load tokenizer and model
    print(f"\nLoading {MODEL_NAME}...")
    tokenizer = DistilBertTokenizer.from_pretrained(MODEL_NAME)
    model = DistilBertForSequenceClassification.from_pretrained(
        MODEL_NAME, num_labels=2,
        id2label={0: "NOT_ADVERSE", 1: "ADVERSE"},
        label2id={"NOT_ADVERSE": 0, "ADVERSE": 1},
    )
    model.to(device)

    # Load data
    print(f"Loading data from {args.data}...")
    train_texts, val_texts, train_labels, val_labels = load_data(args.data)

    if len(train_texts) < 50:
        print(f"\nWARNING: Only {len(train_texts)} training examples.")
        print("For best results, run more vendor assessments to generate more findings,")
        print("then re-export with: python3 ml/export_training_data.py")
        print("Continuing with available data...\n")

    # Create datasets
    train_dataset = FindingsDataset(train_texts, train_labels, tokenizer)
    val_dataset = FindingsDataset(val_texts, val_labels, tokenizer)

    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE)

    # Optimizer and scheduler
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
    )
    total_steps = len(train_loader) * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=total_steps // 10, num_training_steps=total_steps
    )

    # Class weights for imbalanced data
    n_adverse = sum(train_labels)
    n_total = len(train_labels)
    if n_adverse > 0 and n_adverse < n_total:
        weight_adverse = n_total / (2 * n_adverse)
        weight_non_adverse = n_total / (2 * (n_total - n_adverse))
        class_weights = torch.tensor([weight_non_adverse, weight_adverse], dtype=torch.float).to(device)
        print(f"Class weights: non-adverse={weight_non_adverse:.2f}, adverse={weight_adverse:.2f}")
    else:
        class_weights = None

    # Training loop
    print(f"\nTraining for {args.epochs} epochs...")
    best_val_acc = 0
    best_epoch = 0

    for epoch in range(args.epochs):
        # Train
        model.train()
        train_loss = 0
        train_correct = 0
        train_total = 0

        for batch in train_loader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)

            outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
            loss = outputs.loss

            if class_weights is not None:
                # Apply class weights manually
                ce_loss = torch.nn.functional.cross_entropy(outputs.logits, labels, weight=class_weights)
                loss = ce_loss

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()

            train_loss += loss.item()
            preds = torch.argmax(outputs.logits, dim=-1)
            train_correct += (preds == labels).sum().item()
            train_total += labels.size(0)

        train_acc = train_correct / train_total if train_total > 0 else 0

        # Validate
        model.eval()
        val_loss = 0
        val_preds_all = []
        val_labels_all = []

        with torch.no_grad():
            for batch in val_loader:
                input_ids = batch["input_ids"].to(device)
                attention_mask = batch["attention_mask"].to(device)
                labels = batch["labels"].to(device)

                outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
                val_loss += outputs.loss.item()

                preds = torch.argmax(outputs.logits, dim=-1)
                val_preds_all.extend(preds.cpu().tolist())
                val_labels_all.extend(labels.cpu().tolist())

        val_acc = sum(p == l for p, l in zip(val_preds_all, val_labels_all)) / len(val_labels_all) if val_labels_all else 0
        avg_train_loss = train_loss / len(train_loader) if train_loader else 0
        avg_val_loss = val_loss / len(val_loader) if val_loader else 0

        print(f"  Epoch {epoch+1}/{args.epochs}: "
              f"train_loss={avg_train_loss:.4f} train_acc={train_acc:.3f} "
              f"val_loss={avg_val_loss:.4f} val_acc={val_acc:.3f}")

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_epoch = epoch + 1
            # Save best model
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            model.save_pretrained(OUTPUT_DIR)
            tokenizer.save_pretrained(OUTPUT_DIR)

    # Final evaluation
    print(f"\nBest validation accuracy: {best_val_acc:.3f} (epoch {best_epoch})")
    print(f"\nClassification Report:")
    print(classification_report(val_labels_all, val_preds_all, target_names=["NOT_ADVERSE", "ADVERSE"]))
    print(f"Confusion Matrix:")
    print(confusion_matrix(val_labels_all, val_preds_all))

    # Save training metadata
    meta = {
        "model": MODEL_NAME,
        "epochs": args.epochs,
        "best_epoch": best_epoch,
        "best_val_acc": best_val_acc,
        "train_size": len(train_texts),
        "val_size": len(val_texts),
        "adverse_pct": sum(train_labels) / len(train_labels) if train_labels else 0,
        "device": str(device),
        "max_length": MAX_LENGTH,
    }
    with open(os.path.join(OUTPUT_DIR, "training_meta.json"), 'w') as f:
        json.dump(meta, f, indent=2)

    print(f"\nModel saved to {OUTPUT_DIR}/")
    print(f"Model size: {sum(f.stat().st_size for f in Path(OUTPUT_DIR).rglob('*') if f.is_file()) / 1e6:.0f} MB")
    print(f"\nNext step: Copy {OUTPUT_DIR}/ into Docker image and use ml/inference.py")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Train Helios Adverse Media Classifier')
    parser.add_argument('--data', default=DEFAULT_DATA, help='Path to training CSV')
    parser.add_argument('--epochs', type=int, default=3, help='Number of training epochs')
    args = parser.parse_args()

    if not os.path.exists(args.data):
        print(f"Training data not found at {args.data}")
        print("Run: python3 ml/export_training_data.py first")
        sys.exit(1)

    train(args)
