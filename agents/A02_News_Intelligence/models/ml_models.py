"""
CIE-OS A02
Phase 6+: Enhanced ML models with ensemble, online learning, calibration, model registry.

Lightweight sklearn models trained on synthetic/rules data.
Can be retrained with real labeled data later.
"""

from __future__ import annotations

import json
import pickle
import time
from pathlib import Path
from typing import Any

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except Exception:
    NUMPY_AVAILABLE = False
    np = None

try:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import VotingClassifier
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression, SGDClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except Exception:
    SKLEARN_AVAILABLE = False

MODEL_DIR = Path(__file__).resolve().parent
CATEGORY_MODEL = MODEL_DIR / "category_model.pkl"
STANCE_MODEL = MODEL_DIR / "stance_model.pkl"
VERIFICATION_MODEL = MODEL_DIR / "verification_model.pkl"
MODEL_REGISTRY = MODEL_DIR / "model_registry.json"

# Extended categories
CATEGORIES = [
    "etf", "hack", "delisting", "regulatory", "fraud", "earnings",
    "partnership", "macro", "product_launch", "executive_change",
    "merger_acquisition", "guidance_change", "dividend", "stock_split",
    "bankruptcy", "clinical_trial", "patent", "contract_win",
    "investigation", "sanctions", "general",
]

STANCE_LABELS = ["support", "deny", "neutral", "question"]
VERIFICATION_LABELS = ["confirmed_true", "likely_true", "unconfirmed", "unverifiable", "likely_false", "confirmed_false", "fabricated"]


def _synthetic_category_data() -> list[tuple[str, str]]:
    """Synthetic training data for category classification (claim, label)."""
    return [
        # etf
        ("SEC approves spot Bitcoin ETF", "etf"),
        ("Bitcoin ETF application rejected by SEC", "etf"),
        ("Ethereum ETF filing submitted", "etf"),
        ("Gold ETF sees record inflows", "etf"),
        ("Spot Bitcoin ETF gets green light", "etf"),
        ("ETF withdrawal filed by issuer", "etf"),
        # hack
        ("Exchange hacked $100M stolen", "hack"),
        ("Bridge exploit drains funds", "hack"),
        ("Smart contract vulnerability exploited", "hack"),
        ("Wallet drained via phishing attack", "hack"),
        ("Protocol hack leads to $50M loss", "hack"),
        ("DeFi protocol exploited for funds", "hack"),
        # delisting
        ("Exchange delists token", "delisting"),
        ("Binance removes trading pairs", "delisting"),
        ("Coinbase delists asset", "delisting"),
        ("Token delisted from major exchange", "delisting"),
        # regulatory
        ("SEC sues exchange for unregistered securities", "regulatory"),
        ("CFTC charges platform", "regulatory"),
        ("New crypto regulation proposed", "regulatory"),
        ("Exchange fined by regulator", "regulatory"),
        ("Regulatory crackdown on stablecoins", "regulatory"),
        ("SEC issues wells notice to exchange", "regulatory"),
        # fraud
        ("Ponzi scheme uncovered", "fraud"),
        ("Rug pull detected", "fraud"),
        ("Fake token scam", "fraud"),
        ("Founder accused of fraud", "fraud"),
        ("Investment scheme turns out to be fraud", "fraud"),
        # earnings
        ("Company beats earnings estimates", "earnings"),
        ("Quarterly revenue misses", "earnings"),
        ("EPS beats expectations", "earnings"),
        ("Guidance raised after earnings", "earnings"),
        ("Earnings call reveals strong growth", "earnings"),
        # partnership
        ("Partnership announced with major bank", "partnership"),
        ("Strategic alliance formed", "partnership"),
        ("Integration with payment network", "partnership"),
        ("Joint venture announced", "partnership"),
        ("Partnership with tech giant announced", "partnership"),
        # macro
        ("Fed raises interest rates", "macro"),
        ("CPI inflation data released", "macro"),
        ("GDP growth exceeds forecasts", "macro"),
        ("Unemployment claims drop", "macro"),
        ("Central bank signals rate cut", "macro"),
        # product_launch
        ("New mainnet launch", "product_launch"),
        ("Protocol v2 released", "product_launch"),
        ("Feature rollout announced", "product_launch"),
        ("Testnet goes live", "product_launch"),
        ("Major upgrade activated", "product_launch"),
        # executive_change
        ("CEO steps down", "executive_change"),
        ("New CFO appointed", "executive_change"),
        ("Founder leaves company", "executive_change"),
        ("Leadership transition announced", "executive_change"),
        # merger_acquisition
        ("Company acquires competitor", "merger_acquisition"),
        ("Merger announced", "merger_acquisition"),
        ("Takeover bid submitted", "merger_acquisition"),
        ("Acquisition of blockchain startup", "merger_acquisition"),
        # guidance_change
        ("Revenue guidance lowered", "guidance_change"),
        ("Outlook raised for next quarter", "guidance_change"),
        ("Full year guidance updated", "guidance_change"),
        # dividend
        ("Dividend increased", "dividend"),
        ("Special dividend declared", "dividend"),
        ("Dividend cut announced", "dividend"),
        # stock_split
        ("Stock split announced", "stock_split"),
        ("Reverse stock split", "stock_split"),
        # bankruptcy
        ("Company files Chapter 11", "bankruptcy"),
        ("Liquidity crisis leads to bankruptcy", "bankruptcy"),
        # clinical_trial
        ("Phase 3 trial successful", "clinical_trial"),
        ("Drug receives FDA approval", "clinical_trial"),
        # patent
        ("Patent granted for technology", "patent"),
        ("Patent infringement lawsuit", "patent"),
        # contract_win
        ("Government contract awarded", "contract_win"),
        ("Major enterprise deal signed", "contract_win"),
        # investigation
        ("DOJ opens investigation", "investigation"),
        ("SEC inquiry launched", "investigation"),
        # sanctions
        ("OFAC sanctions entity", "sanctions"),
        ("Treasury adds to SDN list", "sanctions"),
        # general
        ("Market moves on rumors", "general"),
        ("Analyst upgrades rating", "general"),
        ("Social media buzz about token", "general"),
        ("Price action drives speculation", "general"),
    ]


def _synthetic_stance_data() -> list[tuple[str, str]]:
    """Synthetic training data for stance classification."""
    return [
        # support
        ("Company confirms partnership with bank", "support"),
        ("Official statement validates the rumors", "support"),
        ("CEO announces product launch", "support"),
        ("SEC filing confirms acquisition", "support"),
        ("Earnings beat confirms strong performance", "support"),
        ("Data shows revenue growth", "support"),
        ("Company verifies the news is accurate", "support"),
        ("Press release confirms the deal", "support"),
        # deny
        ("Company denies acquisition rumors", "deny"),
        ("CEO calls reports false", "deny"),
        ("Official statement refutes claims", "deny"),
        ("No evidence of hack found", "deny"),
        ("Rumors of bankruptcy are false", "deny"),
        ("Exchange denies delisting plans", "deny"),
        ("Firm rejects the allegations", "deny"),
        ("Statement contradicts the rumors", "deny"),
        # neutral
        ("Analyst discusses potential outcomes", "neutral"),
        ("Report examines market impact", "neutral"),
        ("Experts weigh in on regulation", "neutral"),
        ("Market reacts to uncertainty", "neutral"),
        ("Sources say talks are ongoing", "neutral"),
        ("Investors await official news", "neutral"),
        ("Commentary on the developing story", "neutral"),
        ("Analysis of possible scenarios", "neutral"),
        # question
        ("Is the ETF approval coming?", "question"),
        ("Will the hack affect prices?", "question"),
        ("What does the merger mean?", "question"),
        ("Can the company survive?", "question"),
        ("Are the earnings real?", "question"),
        ("Should investors buy the dip?", "question"),
        ("When will the announcement happen?", "question"),
        ("How will this impact the market?", "question"),
    ]


def _synthetic_verification_data() -> list[tuple[str, str]]:
    """Synthetic training data for verification (text + source context, label)."""
    return [
        # confirmed_true
        ("SEC official press release confirms ETF approval", "confirmed_true"),
        ("Company 8-K filing announces merger", "confirmed_true"),
        ("FDA website shows drug approval", "confirmed_true"),
        ("Exchange blog post confirms listing", "confirmed_true"),
        ("Government gazette publishes regulation", "confirmed_true"),
        ("Official regulatory filing confirms", "confirmed_true"),
        # likely_true
        ("Reuters reports ETF approval citing sources", "likely_true"),
        ("Bloomberg confirms merger talks", "likely_true"),
        ("Wall Street Journal reports earnings beat", "likely_true"),
        ("Financial Times cites insider on acquisition", "likely_true"),
        ("CNBC reports partnership announcement", "likely_true"),
        ("Major outlet reports citing officials", "likely_true"),
        # unconfirmed
        ("Twitter user claims insider info", "unconfirmed"),
        ("Reddit post speculates on partnership", "unconfirmed"),
        ("Blog post cites unnamed sources", "unconfirmed"),
        ("Forum discussion about potential hack", "unconfirmed"),
        ("Telegram channel shares rumor", "unconfirmed"),
        ("Anonymous account makes claim", "unconfirmed"),
        # unverifiable
        ("Anonymous source makes claim", "unverifiable"),
        ("Unattributed quote in article", "unverifiable"),
        ("Rumor with no source cited", "unverifiable"),
        ("Claim without evidence", "unverifiable"),
        ("Hearsay with no attribution", "unverifiable"),
        # likely_false
        ("Satire site publishes fake news", "likely_false"),
        ("Known fake news domain posts", "likely_false"),
        ("Claim contradicted by multiple sources", "likely_false"),
        ("Meme account posts as news", "likely_false"),
        ("Clickbait site fabricates story", "likely_false"),
        # confirmed_false
        ("Company officially denies and provides evidence", "confirmed_false"),
        ("Regulator issues statement refuting claim", "confirmed_false"),
        ("Court ruling disproves allegation", "confirmed_false"),
        ("Audit shows no fraud occurred", "confirmed_false"),
        ("Official investigation clears company", "confirmed_false"),
        # fabricated
        ("The Onion publishes crypto satire", "fabricated"),
        ("Babylon Bee crypto parody", "fabricated"),
        ("Clickbait site fabricates quote", "fabricated"),
        ("Deepfake video of CEO", "fabricated"),
        ("AI-generated fake press release", "fabricated"),
        ("Satirical article mistaken for real", "fabricated"),
    ]


def _meta_features(text: str) -> dict:
    """Extract meta features from text for enhanced classification."""
    features = {}
    features["length"] = len(text)
    features["word_count"] = len(text.split())
    features["uppercase_ratio"] = sum(1 for c in text if c.isupper()) / max(len(text), 1)
    features["digit_count"] = sum(1 for c in text if c.isdigit())
    features["dollar_sign"] = 1 if "$" in text else 0
    features["question_mark"] = 1 if "?" in text else 0
    features["exclamation_mark"] = 1 if "!" in text else 0
    features["url_present"] = 1 if "http" in text.lower() else 0
    features["source_like"] = 1 if any(s in text.lower() for s in ["reuters", "bloomberg", "cnbc", "wsj", "ft.com", "sec.gov", "official", "filing", "statement"]) else 0
    features["social_like"] = 1 if any(s in text.lower() for s in ["twitter", "reddit", "telegram", "discord", "rumor", "speculation", "unconfirmed"]) else 0
    features["negation_words"] = sum(1 for w in ["not", "denies", "refutes", "false", "fake", "untrue", "debunked", "rejects"] if w in text.lower())
    features["affirmation_words"] = sum(1 for w in ["confirms", "announces", "official", "verified", "validated", "approves", "confirmed"] if w in text.lower())
    return features


class MetaFeatureExtractor:
    """Extract meta features for classifier enhancement."""
    
    def __init__(self):
        self.feature_names = [
            "length", "word_count", "uppercase_ratio", "digit_count",
            "dollar_sign", "question_mark", "exclamation_mark",
            "url_present", "source_like", "social_like",
            "negation_words", "affirmation_words"
        ]
    
    def fit(self, X, y=None):
        return self
    
    def transform(self, X):
        if hasattr(X, "__iter__") and not isinstance(X, str):
            return [list(_meta_features(x).values()) for x in X]
        return [list(_meta_features(X).values())]
    
    def fit_transform(self, X, y=None):
        return self.transform(X)
    
    def get_feature_names_out(self, input_features=None):
        return self.feature_names


class EnhancedPipeline:
    """Enhanced pipeline with meta features and ensemble."""
    
    def __init__(self, labels: list[str], use_ensemble: bool = True, use_online: bool = False, calibrate: bool = True):
        self.labels = labels
        self.use_ensemble = use_ensemble and SKLEARN_AVAILABLE
        self.use_online = use_online and SKLEARN_AVAILABLE
        self.calibrate = calibrate and SKLEARN_AVAILABLE
        self.pipeline = None
        self.online_clf = None
        self._version = "1.0"
        self._trained_at = None
        self._metrics = {}
    
    def _make_base_pipeline(self, use_char_ngrams: bool = True) -> Pipeline:
        """Create base TF-IDF + LogisticRegression pipeline."""
        if not SKLEARN_AVAILABLE:
            return None
        
        vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=5000,
            min_df=1,
            sublinear_tf=True,
            strip_accents="unicode"
        )
        
        if use_char_ngrams:
            # Combine word and char n-grams for better generalization
            from sklearn.feature_extraction.text import FeatureUnion
            char_vectorizer = TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(3, 5),
                max_features=3000,
                min_df=1,
                sublinear_tf=True
            )
            vectorizer = FeatureUnion([
                ("word", vectorizer),
                ("char", char_vectorizer),
            ])
        
        clf = LogisticRegression(
            max_iter=1000,
            class_weight="balanced",
            random_state=42,
            solver="lbfgs",
            C=1.0
        )
        
        return Pipeline([
            ("tfidf", vectorizer),
            ("clf", clf),
        ])
    
    def _make_ensemble(self) -> VotingClassifier:
        """Create voting ensemble of diverse classifiers."""
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.naive_bayes import MultinomialNB
        from sklearn.svm import LinearSVC
        
        base = self._make_base_pipeline()
        
        # Diverse classifiers
        rf_pipe = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=3000, min_df=1)),
            ("clf", RandomForestClassifier(n_estimators=100, class_weight="balanced", random_state=42, n_jobs=-1)),
        ])
        
        nb_pipe = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=5000, min_df=1)),
            ("clf", MultinomialNB(alpha=0.1)),
        ])
        
        svc_pipe = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=3000, min_df=1)),
            ("clf", LinearSVC(class_weight="balanced", random_state=42, max_iter=2000, dual=True)),
        ])
        
        return VotingClassifier(
            estimators=[
                ("lr", base),
                ("rf", rf_pipe),
                ("nb", nb_pipe),
                ("svc", svc_pipe),
            ],
            voting="soft",
            weights=[2, 1, 1, 1],  # LR gets higher weight
        )
    
    def train(self, X: list[str], y: list[str]) -> dict:
        """Train the model with optional ensemble and calibration."""
        if not SKLEARN_AVAILABLE:
            return {"error": "sklearn not available"}
        
        start = time.time()
        
        # Use ensemble or base pipeline
        if self.use_ensemble and len(X) >= 20:
            self.pipeline = self._make_ensemble()
        else:
            self.pipeline = self._make_base_pipeline()
        
        # Train
        self.pipeline.fit(X, y)
        
        # Calibrate probabilities
        if self.calibrate and len(X) >= 30:
            # Use a small holdout for calibration
            X_train, X_cal, y_train, y_cal = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y
            )
            self.pipeline.fit(X_train, y_train)
            self.pipeline = CalibratedClassifierCV(
                self.pipeline, method="isotonic", cv="prefit"
            )
            self.pipeline.fit(X_cal, y_cal)
        else:
            self.pipeline.fit(X, y)
        
        # Online learning setup
        if self.use_online:
            self.online_clf = Pipeline([
                ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=5000)),
                ("clf", SGDClassifier(
                    loss="log_loss",
                    class_weight="balanced",
                    random_state=42,
                    max_iter=1000,
                    alpha=0.0001
                )),
            ])
            self.online_clf.fit(X, y)
        
        self._trained_at = time.time()
        self._version = f"1.0.{int(self._trained_at)}"
        
        # Compute basic metrics
        train_acc = self.pipeline.score(X, y)
        self._metrics = {
            "train_accuracy": float(train_acc),
            "n_samples": len(X),
            "n_classes": len(set(y)),
            "use_ensemble": self.use_ensemble,
            "calibrated": self.calibrate,
            "training_time_sec": time.time() - start,
        }
        
        return self._metrics
    
    def partial_fit(self, X: list[str], y: list[str]) -> dict:
        """Online update with new data."""
        if not self.use_online or self.online_clf is None:
            return {"error": "Online learning not enabled"}
        
        self.online_clf.partial_fit(X, y, classes=self.labels)
        return {"status": "updated", "n_samples": len(X)}
    
    def predict(self, X: list[str]) -> list[str]:
        if self.pipeline is None:
            return ["unconfirmed"] * len(X)
        return self.pipeline.predict(X)
    
    def predict_proba(self, X: list[str]) -> list[dict[str, float]]:
        if self.pipeline is None or not hasattr(self.pipeline, "predict_proba"):
            return [{} for _ in X]
        proba = self.pipeline.predict_proba(X)
        return [dict(zip(self.pipeline.classes_, map(float, p))) for p in proba]
    
    def save(self, path: Path) -> bool:
        """Save model with metadata."""
        if self.pipeline is None:
            return False
        try:
            metadata = {
                "pipeline": self.pipeline,
                "labels": self.labels,
                "version": self._version,
                "trained_at": self._trained_at,
                "metrics": self._metrics,
                "use_ensemble": self.use_ensemble,
                "calibrated": self.calibrate,
            }
            with path.open("wb") as f:
                pickle.dump(metadata, f)
            return True
        except Exception:
            return False
    
    @classmethod
    def load(cls, path: Path, labels: list[str]) -> "EnhancedPipeline | None":
        """Load model with metadata."""
        if not SKLEARN_AVAILABLE:
            return None
        try:
            with path.open("rb") as f:
                metadata = pickle.load(f)
            if isinstance(metadata, Pipeline):
                # Legacy format
                instance = cls(labels)
                instance.pipeline = metadata
                return instance
            instance = cls(
                labels,
                use_ensemble=metadata.get("use_ensemble", True),
                calibrate=metadata.get("calibrated", True),
            )
            instance.pipeline = metadata["pipeline"]
            instance._version = metadata.get("version", "1.0")
            instance._trained_at = metadata.get("trained_at")
            instance._metrics = metadata.get("metrics", {})
            return instance
        except Exception:
            return None
    
    def get_metadata(self) -> dict:
        return {
            "version": self._version,
            "trained_at": self._trained_at,
            "metrics": self._metrics,
            "labels": self.labels,
            "use_ensemble": self.use_ensemble,
            "calibrated": self.calibrate,
        }


class MLModels:
    """Lazy-loaded enhanced ML models with fallback to rules."""
    
    def __init__(self) -> None:
        self._category: EnhancedPipeline | None = None
        self._stance: EnhancedPipeline | None = None
        self._verification: EnhancedPipeline | None = None
        self._registry = self._load_registry()
    
    def _load_registry(self) -> dict:
        if MODEL_REGISTRY.exists():
            try:
                with MODEL_REGISTRY.open("r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"models": {}, "current": {}}
    
    def _save_registry(self) -> None:
        try:
            with MODEL_REGISTRY.open("w") as f:
                json.dump(self._registry, f, indent=2)
        except Exception:
            pass
    
    def _get_or_train(self, model_path: Path, synthetic_fn, labels: list[str], 
                      use_ensemble: bool = True, calibrate: bool = True) -> EnhancedPipeline | None:
        if not SKLEARN_AVAILABLE:
            return None
        
        # Try loading existing
        model = EnhancedPipeline.load(model_path, labels)
        if model is not None:
            # Check if we should retrain (e.g., new data available)
            return model
        
        # Train new
        data = synthetic_fn()
        X = [d[0] for d in data]
        y = [d[1] for d in data]
        
        model = EnhancedPipeline(labels, use_ensemble=use_ensemble, calibrate=calibrate)
        metrics = model.train(X, y)
        
        # Save
        model.save(model_path)
        
        # Update registry
        self._registry["models"][model_path.name] = model.get_metadata()
        self._registry["current"][model_path.stem] = model_path.name
        self._save_registry()
        
        return model
    
    def category(self, text: str) -> str:
        if self._category is None:
            self._category = self._get_or_train(CATEGORY_MODEL, _synthetic_category_data, CATEGORIES)
        if self._category is None:
            from agents.A02_News_Intelligence.intelligence.history import classify_category as rule_classify
            return rule_classify(text)
        return self._category.predict([text])[0]
    
    def category_proba(self, text: str) -> dict[str, float] | None:
        if self._category is None:
            self._category = self._get_or_train(CATEGORY_MODEL, _synthetic_category_data, CATEGORIES)
        if self._category is None:
            return None
        proba = self._category.predict_proba([text])
        return proba[0] if proba else None
    
    def stance(self, text: str) -> str:
        if self._stance is None:
            self._stance = self._get_or_train(STANCE_MODEL, _synthetic_stance_data, STANCE_LABELS)
        if self._stance is None:
            from agents.A02_News_Intelligence.intelligence.stance import classify_stance as rule_stance
            return rule_stance(text)
        return self._stance.predict([text])[0]
    
    def stance_proba(self, text: str) -> dict[str, float] | None:
        if self._stance is None:
            self._stance = self._get_or_train(STANCE_MODEL, _synthetic_stance_data, STANCE_LABELS)
        if self._stance is None:
            return None
        proba = self._stance.predict_proba([text])
        return proba[0] if proba else None
    
    def verification(self, text: str) -> str:
        if self._verification is None:
            self._verification = self._get_or_train(VERIFICATION_MODEL, _synthetic_verification_data, VERIFICATION_LABELS)
        if self._verification is None:
            return "unconfirmed"
        return self._verification.predict([text])[0]
    
    def verification_proba(self, text: str) -> dict[str, float] | None:
        if self._verification is None:
            self._verification = self._get_or_train(VERIFICATION_MODEL, _synthetic_verification_data, VERIFICATION_LABELS)
        if self._verification is None:
            return None
        proba = self._verification.predict_proba([text])
        return proba[0] if proba else None
    
    def get_model_info(self) -> dict:
        """Get info about all loaded models."""
        info = {}
        for name, model in [("category", self._category), ("stance", self._stance), ("verification", self._verification)]:
            if model is not None:
                info[name] = model.get_metadata()
        return info
    
    def retrain_with_data(self, training_data: list[dict]) -> dict:
        """Retrain models with new labeled data."""
        results = {}
        
        # Category
        cat_data = [(d["text"], d["category"]) for d in training_data if "category" in d]
        if len(cat_data) >= 10:
            X, y = zip(*cat_data)
            self._category = EnhancedPipeline(CATEGORIES)
            metrics = self._category.train(list(X), list(y))
            self._category.save(CATEGORY_MODEL)
            results["category"] = metrics
        
        # Stance
        stance_data = [(d["text"], d["stance"]) for d in training_data if "stance" in d]
        if len(stance_data) >= 10:
            X, y = zip(*stance_data)
            self._stance = EnhancedPipeline(STANCE_LABELS)
            metrics = self._stance.train(list(X), list(y))
            self._stance.save(STANCE_MODEL)
            results["stance"] = metrics
        
        # Verification
        ver_data = [(d["text"], d["verification"]) for d in training_data if "verification" in d]
        if len(ver_data) >= 10:
            X, y = zip(*ver_data)
            self._verification = EnhancedPipeline(VERIFICATION_LABELS)
            metrics = self._verification.train(list(X), list(y))
            self._verification.save(VERIFICATION_MODEL)
            results["verification"] = metrics
        
        return results
    
    def online_update(self, text: str, label: str, task: str) -> dict:
        """Update model online with single sample."""
        model = getattr(self, f"_{task}", None)
        if model is None or not model.use_online:
            return {"error": f"Online learning not available for {task}"}
        return model.partial_fit([text], [label])


# Singleton
_models: MLModels | None = None


def get_models() -> MLModels:
    global _models
    if _models is None:
        _models = MLModels()
    return _models


def classify_category_ml(text: str) -> str:
    """ML-enhanced category classification with rule fallback."""
    return get_models().category(text)


def classify_category_ml_proba(text: str) -> dict[str, float] | None:
    """Category classification with probabilities."""
    return get_models().category_proba(text)


def classify_stance_ml(text: str) -> str:
    """ML-enhanced stance classification with rule fallback."""
    return get_models().stance(text)


def classify_stance_ml_proba(text: str) -> dict[str, float] | None:
    """Stance classification with probabilities."""
    return get_models().stance_proba(text)


def classify_verification_ml(text: str) -> str:
    """ML-enhanced verification with rule fallback."""
    return get_models().verification(text)


def verification_proba_ml(text: str) -> dict[str, float] | None:
    """Verification probabilities if ML available."""
    return get_models().verification_proba(text)


def retrain_models(training_data: list[dict]) -> dict:
    """Retrain all models with new labeled data."""
    return get_models().retrain_with_data(training_data)


def online_update(text: str, label: str, task: str) -> dict:
    """Online update for a specific model."""
    return get_models().online_update(text, label, task)


def get_model_info() -> dict:
    """Get metadata for all models."""
    return get_models().get_model_info()


__all__ = [
    "CATEGORIES",
    "STANCE_LABELS",
    "VERIFICATION_LABELS",
    "get_models",
    "classify_category_ml",
    "classify_category_ml_proba",
    "classify_stance_ml",
    "classify_stance_ml_proba",
    "classify_verification_ml",
    "verification_proba_ml",
    "retrain_models",
    "online_update",
    "get_model_info",
]