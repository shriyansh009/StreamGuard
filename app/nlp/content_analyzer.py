"""StreamGuard NLP Content Analysis Engine powered by Meta's FastText.

Performs supervised machine learning toxicity classification on streaming
chat messages, slurs, threats, harassment, profanity, and spam detection
using Meta FastText, with native Hugging Face Hub integration for model distribution.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Tuple

import fasttext
from app.nlp.training_data import SEED_MODERATION_DATA

logger = logging.getLogger(__name__)


class ContentAnalyzer:
    """ML-powered NLP content analysis engine for stream moderation using Meta's FastText.

    Analyzes text streams for hate speech, profanity, physical threats,
    harassment, and repetitive spam patterns using Meta FastText supervised
    embeddings with subword n-grams, supporting pre-trained models hosted
    on Hugging Face Hub.
    """

    # Category severity weights as specified
    WEIGHT_THREAT: float = 0.95
    WEIGHT_HATE_SPEECH: float = 0.90
    WEIGHT_PROFANITY: float = 0.70
    WEIGHT_HARASSMENT: float = 0.60
    WEIGHT_SPAM: float = 0.40
    WEIGHT_CLEAN: float = 0.00

    CATEGORY_WEIGHTS: Dict[str, float] = {
        "threat": 0.95,
        "hate_speech": 0.90,
        "profanity": 0.70,
        "harassment": 0.60,
        "spam": 0.40,
        "clean": 0.00,
    }

    # Default model cache location
    DEFAULT_MODEL_DIR: Path = Path(__file__).parent / "models"
    DEFAULT_MODEL_FILE: Path = DEFAULT_MODEL_DIR / "fasttext_streamguard.bin"

    def __init__(
        self,
        model_path: Optional[str] = None,
        hf_repo_id: Optional[str] = None,
        hf_filename: Optional[str] = None,
        hf_token: Optional[str] = None,
        patterns: Optional[List[Tuple[str, float]]] = None,
        category_map: Optional[Dict[str, str]] = None,
    ) -> None:
        """Initialize the FastText-powered ContentAnalyzer.

        Args:
            model_path: Optional path to a local FastText (.bin) binary model.
            hf_repo_id: Optional Hugging Face Hub repository containing a FastText model.
            hf_filename: Optional filename within the Hugging Face repo (default: 'model.bin').
            hf_token: Optional Hugging Face Hub authentication token.
            patterns: Optional custom regex pattern list for hybrid or backward compatibility.
            category_map: Optional mapping of custom patterns to category names.
        """
        self.model: Optional[Any] = None
        self.model_source: str = "uninitialized"

        # Optional custom patterns for backward compatibility
        self.raw_patterns = patterns
        self.category_map = category_map or {}
        self._compiled_patterns: List[Tuple[Pattern[str], float, str, bool]] = []
        if self.raw_patterns:
            for pat_str, weight in self.raw_patterns:
                try:
                    is_case_sensitive = "[A-Z]" in pat_str and "[a-z]" not in pat_str
                    flags = 0 if is_case_sensitive else re.IGNORECASE
                    compiled = re.compile(pat_str, flags)
                    category = self.category_map.get(pat_str, self._infer_category(weight))
                    self._compiled_patterns.append((compiled, float(weight), category, is_case_sensitive))
                except re.error as e:
                    logger.error("Failed to compile custom pattern '%s': %s", pat_str, e)

        # Resolve model configuration from settings if not explicitly provided
        from app.config import get_settings
        settings = get_settings()

        resolved_hf_repo = hf_repo_id or settings.HUGGINGFACE_REPO_ID
        resolved_hf_file = hf_filename or settings.HUGGINGFACE_FILENAME
        resolved_hf_token = hf_token or settings.HUGGINGFACE_TOKEN
        resolved_model_path = model_path or settings.FASTTEXT_MODEL_PATH

        # 1. Hugging Face Hub priority if specified
        if resolved_hf_repo:
            try:
                self.load_from_huggingface(
                    repo_id=resolved_hf_repo,
                    filename=resolved_hf_file,
                    token=resolved_hf_token,
                )
                return
            except Exception as e:
                logger.warning(
                    "Failed to download FastText model from Hugging Face '%s/%s': %s. Falling back to local model.",
                    resolved_hf_repo,
                    resolved_hf_file,
                    e,
                )

        # 2. Local explicit model path if specified
        if resolved_model_path and os.path.exists(resolved_model_path):
            self.load_model(resolved_model_path)
            return

        # 3. Default bundled/cached local model file
        if self.DEFAULT_MODEL_FILE.exists():
            self.load_model(str(self.DEFAULT_MODEL_FILE))
            return

        # 4. Auto-train FastText classifier on seed moderation data
        logger.info("No pre-existing FastText model found. Auto-training seed moderation model...")
        self.DEFAULT_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self.train_model(
            training_data=SEED_MODERATION_DATA,
            output_path=str(self.DEFAULT_MODEL_FILE),
        )

    @staticmethod
    def _infer_category(weight: float) -> str:
        """Infer category name from weight when no explicit category is mapped."""
        if weight >= 0.95:
            return "threat"
        if weight >= 0.90:
            return "hate_speech"
        if weight >= 0.70:
            return "profanity"
        if weight >= 0.60:
            return "harassment"
        return "spam"

    def load_from_huggingface(
        self,
        repo_id: str,
        filename: str = "model.bin",
        token: Optional[str] = None,
    ) -> str:
        """Download and load a FastText model directly from Hugging Face Hub.

        Args:
            repo_id: Hugging Face repository ID (e.g., 'facebook/fasttext-language-identification').
            filename: Target binary file in the repository (e.g., 'model.bin').
            token: Optional Hugging Face authentication token.

        Returns:
            The local cached filepath of the downloaded model.
        """
        from huggingface_hub import hf_hub_download

        logger.info("Downloading FastText model from Hugging Face Hub: %s/%s", repo_id, filename)
        downloaded_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            token=token,
        )
        self.load_model(downloaded_path)
        self.model_source = f"huggingface:{repo_id}/{filename}"
        logger.info("Successfully loaded FastText model from Hugging Face: %s", self.model_source)
        return downloaded_path

    def load_model(self, model_path: str) -> None:
        """Load a FastText binary model from local disk.

        Args:
            model_path: Path to the .bin file.
        """
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"FastText model file not found at: {model_path}")

        logger.info("Loading FastText model from %s", model_path)
        self.model = fasttext.load_model(str(model_path))
        self.model_source = str(model_path)
        logger.info("FastText model loaded successfully. Labels: %s", self.model.labels)

    def train_model(
        self,
        training_data: Optional[List[Tuple[str, str]]] = None,
        output_path: Optional[str] = None,
        epoch: int = 100,
        lr: float = 0.7,
        word_ngrams: int = 3,
        dim: int = 50,
    ) -> str:
        """Train a supervised FastText classifier with subword n-grams and multi-label support.

        Args:
            training_data: List of (label, text) tuples. Defaults to SEED_MODERATION_DATA.
            output_path: Target .bin file path. Defaults to DEFAULT_MODEL_FILE.
            epoch: Number of training epochs.
            lr: Learning rate.
            word_ngrams: Maximum length of word n-grams.
            dim: Size of word vectors.

        Returns:
            Path to the saved trained model file.
        """
        data = training_data or SEED_MODERATION_DATA
        save_path = output_path or str(self.DEFAULT_MODEL_FILE)

        # Prepare temporary training file in FastText format: __label__<cat1> __label__<cat2> <text>
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tmp_file:
            for label, text in data:
                normalized = self.normalize_text(text)
                labels_formatted = " ".join([f"__label__{l.strip()}" for l in label.split() if l.strip()])
                tmp_file.write(f"{labels_formatted} {normalized}\n")
            tmp_path = tmp_file.name

        try:
            logger.info("Training FastText supervised model on %d samples...", len(data))
            trained_model = fasttext.train_supervised(
                input=tmp_path,
                epoch=epoch,
                lr=lr,
                wordNgrams=word_ngrams,
                minCount=1,
                minn=2,
                maxn=5,
                dim=dim,
                loss="ova",
            )
            # Ensure destination directory exists and save model
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            trained_model.save_model(save_path)
            self.model = trained_model
            self.model_source = save_path
            logger.info("FastText model trained and saved to %s", save_path)
            return save_path
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def normalize_text(self, text: str) -> str:
        """Lowercase, strip, and normalize unicode text using NFKC.

        Args:
            text: Raw input string to normalize.

        Returns:
            Normalized lowercase string with unicode compatibility characters canonicalized.
        """
        if not text:
            return ""
        try:
            normalized = unicodedata.normalize("NFKC", text)
            return normalized.strip().lower()
        except Exception as e:
            logger.warning("Error normalizing text: %s. Falling back to basic strip/lower.", e)
            return str(text).strip().lower()

    def predict_proba(self, text: str) -> Dict[str, float]:
        """Predict confidence probabilities for each moderation category.

        Args:
            text: Raw input text.

        Returns:
            Dictionary mapping category names to probability scores (0.0 to 1.0).
        """
        if not self.model or not text or not text.strip():
            return {cat: 0.0 for cat in self.CATEGORY_WEIGHTS}

        normalized = self.normalize_text(text)
        k_labels = len(self.model.labels)
        raw_labels, raw_probs = self.model.predict(normalized, k=k_labels)

        result: Dict[str, float] = {}
        for lbl, prob in zip(raw_labels, raw_probs):
            clean_lbl = lbl.replace("__label__", "")
            result[clean_lbl] = float(prob)

        return result

    def analyze(self, text: str) -> Dict[str, Any]:
        """Analyze message text for toxicity, threats, profanity, harassment, and spam.

        Uses Meta's FastText supervised classifier to compute ML-based toxicity
        scores and detect violation categories. Also evaluates custom patterns
        if configured.

        Args:
            text: Raw input text from the message stream.

        Returns:
            dict containing:
                - toxicity_score: float (0.0 - 1.0, ML-predicted severity score)
                - flagged: bool (True if score > 0.5)
                - matched_patterns: list[str] (names of matched violation categories)
                - action_taken: str ('allowed' if score < 0.3, 'flagged' if 0.3 <= score <= 0.7, 'blocked' if score > 0.7)
        """
        if not text or not text.strip():
            return {
                "toxicity_score": 0.0,
                "flagged": False,
                "matched_patterns": [],
                "action_taken": "allowed",
            }

        try:
            normalized_lower = self.normalize_text(text)
            matched_weights: List[float] = []
            matched_categories: List[str] = []

            # 1. Custom regex patterns evaluation (if custom patterns were explicitly provided)
            if self._compiled_patterns:
                normalized_cased = unicodedata.normalize("NFKC", text).strip()
                for compiled, weight, category, is_case_sensitive in self._compiled_patterns:
                    target_text = normalized_cased if is_case_sensitive else normalized_lower
                    if compiled.search(target_text):
                        matched_weights.append(weight)
                        if category not in matched_categories:
                            matched_categories.append(category)

            # 2. FastText ML Model Inference
            if self.model is not None and not self.raw_patterns:
                # Predict multi-label violations with OVA threshold
                raw_labels, raw_probs = self.model.predict(normalized_lower, k=-1, threshold=0.15)

                if not raw_labels:
                    raw_labels, raw_probs = self.model.predict(normalized_lower, k=1)

                predictions: Dict[str, float] = {}
                for lbl, prob in zip(raw_labels, raw_probs):
                    cat = lbl.replace("__label__", "")
                    predictions[cat] = float(prob)

                has_toxic = any(
                    cat in predictions and cat != "clean" and predictions[cat] >= 0.15
                    for cat in self.CATEGORY_WEIGHTS
                )

                if not has_toxic and predictions.get("clean", 0.0) >= 0.30:
                    pass  # Clean message
                else:
                    for cat, prob in predictions.items():
                        if cat != "clean" and cat in self.CATEGORY_WEIGHTS and prob >= 0.15:
                            matched_weights.append(self.CATEGORY_WEIGHTS[cat])
                            if cat not in matched_categories:
                                matched_categories.append(cat)

                    # If still empty but top label is a category
                    if not matched_categories and raw_labels:
                        top_cat = raw_labels[0].replace("__label__", "")
                        if top_cat != "clean" and top_cat in self.CATEGORY_WEIGHTS:
                            matched_weights.append(self.CATEGORY_WEIGHTS[top_cat])
                            matched_categories.append(top_cat)

            # 3. Compute ML toxicity score
            if not matched_weights:
                toxicity_score = 0.0
            else:
                # Weighted average of detected violation categories
                toxicity_score = round(sum(matched_weights) / len(matched_weights), 4)
                toxicity_score = max(0.0, min(1.0, toxicity_score))

            # 4. Moderation action thresholds
            flagged = toxicity_score > 0.5

            if toxicity_score < 0.3:
                action_taken = "allowed"
            elif toxicity_score <= 0.7:
                action_taken = "flagged"
            else:
                action_taken = "blocked"

            return {
                "toxicity_score": toxicity_score,
                "flagged": flagged,
                "matched_patterns": matched_categories,
                "action_taken": action_taken,
            }

        except Exception as e:
            logger.error("Unexpected error during FastText text analysis: %s", e, exc_info=True)
            return {
                "toxicity_score": 0.0,
                "flagged": False,
                "matched_patterns": [],
                "action_taken": "allowed",
            }
