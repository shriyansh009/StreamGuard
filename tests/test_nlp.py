"""Unit tests for StreamGuard NLP Content Analyzer Engine."""

import pytest
from app.nlp.content_analyzer import ContentAnalyzer


@pytest.fixture
def analyzer() -> ContentAnalyzer:
    return ContentAnalyzer()


class TestContentAnalyzer:
    """Tests covering regex pattern matching, scoring, thresholds, and normalization."""

    def test_clean_message_allowed(self, analyzer: ContentAnalyzer):
        text = "Hello everyone, hope you are having a wonderful stream!"
        result = analyzer.analyze(text)

        assert result["toxicity_score"] == 0.0
        assert result["flagged"] is False
        assert result["matched_patterns"] == []
        assert result["action_taken"] == "allowed"

    def test_empty_or_whitespace_message(self, analyzer: ContentAnalyzer):
        for empty_val in ["", "   ", "\n\t", None]:
            result = analyzer.analyze(empty_val)
            assert result["toxicity_score"] == 0.0
            assert result["flagged"] is False
            assert result["matched_patterns"] == []
            assert result["action_taken"] == "allowed"

    def test_threat_detection_blocked(self, analyzer: ContentAnalyzer):
        threats = [
            "I will kill you right now",
            "Go die and kys",
            "I'll stab you if you come here",
            "Hope you die in a fire",
            "I will bomb your house tomorrow",
        ]
        for msg in threats:
            result = analyzer.analyze(msg)
            assert "threat" in result["matched_patterns"]
            assert result["toxicity_score"] >= 0.90
            assert result["action_taken"] == "blocked"
            assert result["flagged"] is True

    def test_hate_speech_detection_blocked(self, analyzer: ContentAnalyzer):
        hate_messages = [
            "gas the jews right now",
            "white power heil hitler",
            "kill all muslims today",
            "subhuman race of parasites",
        ]
        for msg in hate_messages:
            result = analyzer.analyze(msg)
            assert "hate_speech" in result["matched_patterns"]
            assert result["toxicity_score"] >= 0.90
            assert result["action_taken"] == "blocked"
            assert result["flagged"] is True

    def test_profanity_detection(self, analyzer: ContentAnalyzer):
        profanities = [
            "What the fucking hell is this?",
            "You are a total asshole",
            "Get this piece of shit out of here",
            "Shut up, bitch",
        ]
        for msg in profanities:
            result = analyzer.analyze(msg)
            assert ("profanity" in result["matched_patterns"] or "harassment" in result["matched_patterns"])
            assert result["toxicity_score"] >= 0.60
            assert result["flagged"] is True

    def test_harassment_detection(self, analyzer: ContentAnalyzer):
        harassments = [
            "You are so ugly and pathetic",
            "Nobody likes you, waste of life",
            "I will doxx your address and leak your photos",
            "Get lost loser",
        ]
        for msg in harassments:
            result = analyzer.analyze(msg)
            assert "harassment" in result["matched_patterns"]
            assert result["toxicity_score"] >= 0.60
            assert result["flagged"] is True

    def test_spam_detection(self, analyzer: ContentAnalyzer):
        # 5+ repeated characters
        res_rep = analyzer.analyze("Wooooooow this is insane!!!!!")
        assert "spam" in res_rep["matched_patterns"]
        assert res_rep["toxicity_score"] == 0.40
        assert res_rep["action_taken"] == "flagged"
        assert res_rep["flagged"] is False  # score 0.40 is not > 0.50

        # ALL CAPS words (6+ characters)
        res_caps = analyzer.analyze("CHECKOUTTHISLINK RIGHTNOW")
        assert "spam" in res_caps["matched_patterns"]

        # Phishing / Crypto spam
        res_crypto = analyzer.analyze("free crypto click here to claim guaranteed profit")
        assert "spam" in res_crypto["matched_patterns"]

        # Repeated words 4+ times
        res_repeat_words = analyzer.analyze("promo promo promo promo")
        assert "spam" in res_repeat_words["matched_patterns"]

    def test_mixed_violations_weighted_average(self, analyzer: ContentAnalyzer):
        # Threat (0.95) and Profanity (0.70)
        msg = "I will kill you, you fucking idiot"
        result = analyzer.analyze(msg)

        assert "threat" in result["matched_patterns"]
        assert "profanity" in result["matched_patterns"]
        # Average: (0.95 + 0.70 + 0.60)/3 = ~0.75 or (0.95 + 0.70)/2 = 0.825
        assert result["toxicity_score"] >= 0.70
        assert result["action_taken"] == "blocked"
        assert result["flagged"] is True

    def test_unicode_normalization(self, analyzer: ContentAnalyzer):
        # Fullwidth or composite characters
        text = "Ｈｅｌｌｏ ｗｏｒｌｄ"
        normalized = analyzer.normalize_text(text)
        assert normalized == "hello world"

    def test_custom_patterns_initialization(self):
        custom_patterns = [(r"\bbannedword\b", 0.85)]
        custom_analyzer = ContentAnalyzer(
            patterns=custom_patterns,
            category_map={r"\bbannedword\b": "custom_filter"},
        )
        result = custom_analyzer.analyze("This message contains bannedword here")
        assert "custom_filter" in result["matched_patterns"]
        assert result["toxicity_score"] == 0.85
        assert result["action_taken"] == "blocked"
        assert result["flagged"] is True

    def test_fasttext_model_predict_proba(self, analyzer: ContentAnalyzer):
        probs = analyzer.predict_proba("I will kill you right now")
        assert isinstance(probs, dict)
        assert "threat" in probs
        assert probs["threat"] > 0.50

    def test_huggingface_hub_download_integration(self, monkeypatch, tmp_path):
        from unittest.mock import MagicMock
        import app.nlp.content_analyzer as ca_module

        # Mock hf_hub_download to return existing model file
        dummy_model_path = str(ContentAnalyzer.DEFAULT_MODEL_FILE)
        mock_hf_download = MagicMock(return_value=dummy_model_path)
        monkeypatch.setattr("huggingface_hub.hf_hub_download", mock_hf_download)

        hf_analyzer = ContentAnalyzer(
            hf_repo_id="facebook/fasttext-content-moderation",
            hf_filename="model.bin",
            hf_token="test-token-123",
        )

        mock_hf_download.assert_called_once_with(
            repo_id="facebook/fasttext-content-moderation",
            filename="model.bin",
            token="test-token-123",
        )
        assert "huggingface:facebook/fasttext-content-moderation/model.bin" in hf_analyzer.model_source

    def test_train_custom_fasttext_model(self, tmp_path):
        custom_data = [
            ("custom_threat", "I will destroy your server"),
            ("clean", "Welcome to the server"),
        ]
        out_path = str(tmp_path / "custom_model.bin")
        analyzer = ContentAnalyzer()
        saved_path = analyzer.train_model(
            training_data=custom_data,
            output_path=out_path,
            epoch=20,
        )
        assert saved_path == out_path
        assert analyzer.model is not None
