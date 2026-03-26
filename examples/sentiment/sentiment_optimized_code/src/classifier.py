"""Sentiment classifier — rule-based text sentiment analysis.

This is the Layer 1 mutation surface. The SOR agent optimizes this file
to maximize accuracy on the golden set.
"""

import re

POSITIVE_WORDS = {
    "good", "great", "love", "amazing", "best", "happy", "fantastic",
    "wonderful", "excellent", "superb", "perfect", "beautiful", "adore",
    "recommend", "glad", "pleasant", "sturdy",
    "easy", "helpful", "exceeded", "better", "easier",
    "surprisingly", "definitely",
}

NEGATIVE_WORDS = {
    "bad", "terrible", "worst", "hate", "awful", "horrible", "waste",
    "disappointed", "garbage", "junk", "frustrating", "dreadful",
    "damaged", "regret", "misleading", "cheaply", "poor", "cheap",
}

POSITIVE_PHRASES = [
    "not bad", "pleasantly surprised", "no complaints",
    "five stars", "do the job", "does the job", "gets the job done",
    "can't complain", "so much easier", "surprisingly sturdy",
    "actually great",
]

NEGATIVE_PHRASES = [
    "waste of money", "not worth", "do not buy", "don't waste",
    "falls apart", "not what i would call a good",
    "not what i'd call good", "wouldn't say",
    "never again", "not impressed",
]

NEUTRAL_PHRASES = [
    "nothing special", "about what you'd expect", "mixed feelings",
    "some features are good", "not great, not terrible",
    "it's fine", "it works but", "not my favorite but",
]


def classify(text: str) -> str:
    """Classify text sentiment as 'positive', 'negative', or 'neutral'.

    Args:
        text: Input text to classify.

    Returns:
        One of: 'positive', 'negative', 'neutral'
    """
    lower = text.lower()

    # Neutral phrase check first — strong neutral signals
    neu_phrase_hits = sum(1 for p in NEUTRAL_PHRASES if p in lower)

    # Phrase-level matching
    pos_phrase_hits = sum(1 for p in POSITIVE_PHRASES if p in lower)
    neg_phrase_hits = sum(1 for p in NEGATIVE_PHRASES if p in lower)

    # Word-level matching with punctuation stripping
    words = re.findall(r"[a-z']+", lower)
    pos_count = sum(1 for w in words if w in POSITIVE_WORDS)
    neg_count = sum(1 for w in words if w in NEGATIVE_WORDS)

    # Negation handling: "not good" flips sentiment
    for i, w in enumerate(words):
        if w in ("not", "don't", "doesn't", "isn't", "wouldn't", "no"):
            if i + 1 < len(words):
                next_w = words[i + 1]
                if next_w in POSITIVE_WORDS:
                    pos_count -= 1
                    neg_count += 1
                elif next_w in NEGATIVE_WORDS:
                    neg_count -= 1
                    pos_count += 1

    total_pos = pos_count + pos_phrase_hits * 2
    total_neg = neg_count + neg_phrase_hits * 2

    # Strong neutral signal overrides weak pos/neg
    if neu_phrase_hits > 0 and abs(total_pos - total_neg) <= 1:
        return "neutral"

    if total_pos > total_neg:
        return "positive"
    elif total_neg > total_pos:
        return "negative"
    else:
        return "neutral"
