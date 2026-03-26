"""Contract tests for the sentiment API (Layer 2).

FROZEN — do not modify.
"""

from src.api import analyze


class TestApiContract:
    """Basic contracts the API must satisfy."""

    def test_returns_dict(self):
        result = analyze("hello world")
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = analyze("great product")
        assert "text" in result
        assert "sentiment" in result
        assert "confidence" in result

    def test_text_echoed(self):
        result = analyze("test input")
        assert result["text"] == "test input"

    def test_sentiment_valid(self):
        result = analyze("I love this")
        assert result["sentiment"] in ("positive", "negative", "neutral")

    def test_confidence_range(self):
        result = analyze("pretty good stuff")
        assert 0.0 <= result["confidence"] <= 1.0

    def test_empty_input(self):
        result = analyze("")
        assert isinstance(result, dict)
        assert result["sentiment"] in ("positive", "negative", "neutral")

    def test_uses_classifier(self):
        """API should agree with the underlying classifier."""
        from src.classifier import classify
        text = "I absolutely love this amazing product!"
        api_result = analyze(text)
        classifier_result = classify(text)
        assert api_result["sentiment"] == classifier_result
