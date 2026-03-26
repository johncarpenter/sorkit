"""Contract tests for the sentiment classifier (Layer 1).

These are binary pass/fail tests. The classifier MUST satisfy all of these
before scored tests run. They test basic functionality, not accuracy.

FROZEN — do not modify.
"""

from src.classifier import classify


class TestClassifierContract:
    """Basic contracts the classifier must satisfy."""

    def test_returns_string(self):
        result = classify("hello world")
        assert isinstance(result, str)

    def test_returns_valid_label(self):
        result = classify("this is a test")
        assert result in ("positive", "negative", "neutral")

    def test_handles_empty_string(self):
        result = classify("")
        assert result in ("positive", "negative", "neutral")

    def test_handles_single_word(self):
        result = classify("great")
        assert result in ("positive", "negative", "neutral")

    def test_handles_long_text(self):
        text = "word " * 1000
        result = classify(text)
        assert result in ("positive", "negative", "neutral")

    def test_handles_special_characters(self):
        result = classify("hello!!! @#$% ???")
        assert result in ("positive", "negative", "neutral")

    def test_handles_mixed_case(self):
        result = classify("GREAT product")
        assert result in ("positive", "negative", "neutral")

    def test_obviously_positive(self):
        """Smoke test: extremely positive text should not be negative."""
        result = classify("I love this, it's amazing and wonderful and great!")
        assert result != "negative"

    def test_obviously_negative(self):
        """Smoke test: extremely negative text should not be positive."""
        result = classify("I hate this, it's terrible and awful and horrible!")
        assert result != "positive"

    def test_deterministic(self):
        """Same input should always produce same output."""
        text = "this is a pretty good product"
        results = [classify(text) for _ in range(10)]
        assert len(set(results)) == 1
