"""Sentiment classifier — rule-based text sentiment analysis.

This is the Layer 1 mutation surface. The SOR agent optimizes this file
to maximize accuracy on the golden set.

Starting point: a deliberately naive implementation with basic word lists.
"""


POSITIVE_WORDS = {"good", "great", "love", "amazing", "best", "happy"}
NEGATIVE_WORDS = {"bad", "terrible", "worst", "hate", "awful", "horrible"}


def classify(text: str) -> str:
    """Classify text sentiment as 'positive', 'negative', or 'neutral'.

    Args:
        text: Input text to classify.

    Returns:
        One of: 'positive', 'negative', 'neutral'
    """
    words = text.lower().split()
    pos_count = sum(1 for w in words if w in POSITIVE_WORDS)
    neg_count = sum(1 for w in words if w in NEGATIVE_WORDS)

    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    else:
        return "neutral"
