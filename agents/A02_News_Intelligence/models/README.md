# A02 News Intelligence Agent — ML Models

Saved sklearn models and training utilities.

## Structure

```
models/
├── __init__.py          # exports: get_models, classify_category_ml, etc.
├── ml_models.py         # MLModels class + synthetic training data + persistence
├── category_model.pkl   # trained category classifier (TF-IDF + LogisticRegression)
├── stance_model.pkl     # trained stance classifier
├── verification_model.pkl # trained verification classifier
```

## Models

All models use `Pipeline(TfidfVectorizer + LogisticRegression)` with:
- ngram_range=(1, 2)
- max_features=5000
- class_weight="balanced"
- random_state=42

### Category Classifier (21 classes)
`classify_category_ml(text)` → category string
- Falls back to `history.classify_category` (rules) if sklearn unavailable

### Stance Classifier (4 classes)
`classify_stance_ml(text)` → support/deny/neutral/question
- Falls back to `stance.classify_stance` (rules)

### Verification Classifier (7 classes)
`classify_verification_ml(text)` → confirmed_true/likely_true/unconfirmed/unverifiable/likely_false/confirmed_false/fabricated
`verification_proba_ml(text)` → dict of label→probability
- Falls back to rules-based `unconfirmed`

## Training Data

Synthetic data in `ml_models.py`:
- `_synthetic_category_data()` — 100+ (claim, category) pairs
- `_synthetic_stance_data()` — 36 (text, stance) pairs
- `_synthetic_verification_data()` — 35 (text+context, verdict) pairs

Models train on first import if `.pkl` not found. Persist to `models/`.

## Retraining

```python
from agents.A02_News_Intelligence.core.phase7 import export_training_data, retrain_ml_models
from agents.A02_News_Intelligence.core.storage import Storage

# Export resolved events as labeled JSON
n = await export_training_data(storage, "training_data.json", min_confidence=0.8)

# Retrain all models
results = retrain_ml_models("training_data.json")
# {"category": True, "verification": True, "direction": True}
```

## Usage

```python
from agents.A02_News_Intelligence.models.ml_models import (
    classify_category_ml,
    classify_stance_ml,
    classify_verification_ml,
    verification_proba_ml,
)

cat = classify_category_ml("SEC approves Bitcoin ETF")  # "etf"
stance = classify_stance_ml("Company confirms partnership")  # "support"
verdict = classify_verification_ml("Official SEC filing confirms")  # "confirmed_true"
proba = verification_proba_ml("Some claim")  # {"CONFIRMED_TRUE": 0.7, ...}
```