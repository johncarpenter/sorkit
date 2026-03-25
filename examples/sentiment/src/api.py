"""Sentiment API — HTTP endpoint wrapping the classifier.

This is the Layer 2 mutation surface. The SOR agent implements and
fixes this file after the classifier is frozen.

Starting point: stub that needs to be implemented.
"""

from src.classifier import classify


def analyze(text: str) -> dict:
    """Analyze sentiment of text and return structured result.

    Args:
        text: Input text to analyze.

    Returns:
        Dict with keys: text, sentiment, confidence
    """
    # TODO: implement
    raise NotImplementedError("API not yet implemented")
