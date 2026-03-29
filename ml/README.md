# Xiphos Helios ML Pipeline

Adverse media classifier using DistilBERT fine-tuning.
Replaces keyword matching in Google News and GDELT connectors with ML-based intent detection.

## Setup (your MacBook Pro M2 Max)

```bash
# Install dependencies
pip3 install -r ml/requirements.txt

# Verify MPS acceleration
python3 -c "import torch; print('MPS:', torch.backends.mps.is_available())"
```

## Training Pipeline

### Step 1: Export training data from live Helios
```bash
python3 ml/export_training_data.py
```
This connects to the live API, pulls all OSINT findings, and labels them using high-confidence heuristics. Output: `ml/training_data.csv`

### Step 2: Train the classifier
```bash
python3 ml/train_classifier.py
```
Fine-tunes DistilBERT on your M2 Max (~10-15 minutes). Output: `ml/model/` directory containing the trained model + tokenizer.

### Step 3: Deploy
Copy `ml/model/` to the runtime model path on the host:
```bash
ssh <deploy-user>@<deploy-host> 'mkdir -p /mnt/volume_sfo3_01/xiphos-data/ml'
scp -r ml/model <deploy-user>@<deploy-host>:/mnt/volume_sfo3_01/xiphos-data/ml/
```
Then rebuild:
```bash
cd /opt/xiphos && docker compose build --no-cache && docker compose up -d
```

The runtime container no longer bakes the model bundle into the image. By default it looks for a model under `/data/ml/model` (or whatever `XIPHOS_ML_MODEL_DIR` points at). The inference module activates only when both the model files and the optional ML packages are present; otherwise connectors fall back to keyword matching.

## How It Works

The classifier replaces this (keyword matching):
```python
is_adverse = any(kw in title for kw in {"fraud", "sanctions", ...})
```

With this (ML inference):
```python
from ml.inference import classify_finding
result = classify_finding("Toyota and Thales partner on connectivity")
# result = {"adverse": False, "confidence": 0.92}
```

## Improving Accuracy

1. Run more vendor assessments in Helios to generate diverse findings
2. Re-export: `python3 ml/export_training_data.py`
3. Retrain: `python3 ml/train_classifier.py --epochs 5`
4. Redeploy the updated model

The model improves as your dataset grows. Target: 2,000+ labeled examples for production-grade accuracy.

## Model Specs

- Base: distilbert-base-uncased (66M parameters, ~250MB)
- Fine-tuning: Binary classification (ADVERSE / NOT_ADVERSE)
- Max sequence length: 128 tokens
- Inference: <50ms per finding on CPU, <10ms on MPS/CUDA
