"""Scored tests for the sentiment classifier (Layer 1).

These tests evaluate the classifier against the golden set and print
metrics to stdout for the oracle to extract.

The oracle extracts:
  ACCURACY: <float>       — overall accuracy (weight: 0.5)
  POS_RECALL: <float>     — recall on positive examples (weight: 0.2)
  NEG_RECALL: <float>     — recall on negative examples (weight: 0.2)
  NEU_RECALL: <float>     — recall on neutral examples (weight: 0.1)

FROZEN — do not modify.
"""

from src.classifier import classify


def test_golden_set_accuracy(golden_set):
    """Evaluate classifier accuracy on the full golden set."""
    correct = 0
    total = len(golden_set)

    # Per-class tracking
    class_correct = {"positive": 0, "negative": 0, "neutral": 0}
    class_total = {"positive": 0, "negative": 0, "neutral": 0}

    for item in golden_set:
        text = item["text"]
        expected = item["label"]
        predicted = classify(text)

        class_total[expected] += 1
        if predicted == expected:
            correct += 1
            class_correct[expected] += 1

    # Overall accuracy
    accuracy = correct / total if total > 0 else 0

    # Per-class recall
    pos_recall = (
        class_correct["positive"] / class_total["positive"]
        if class_total["positive"] > 0
        else 0
    )
    neg_recall = (
        class_correct["negative"] / class_total["negative"]
        if class_total["negative"] > 0
        else 0
    )
    neu_recall = (
        class_correct["neutral"] / class_total["neutral"]
        if class_total["neutral"] > 0
        else 0
    )

    # Print metrics for oracle extraction
    print(f"ACCURACY: {accuracy:.4f}")
    print(f"POS_RECALL: {pos_recall:.4f}")
    print(f"NEG_RECALL: {neg_recall:.4f}")
    print(f"NEU_RECALL: {neu_recall:.4f}")

    # Print confusion details for the agent to learn from
    print(f"\nResults: {correct}/{total} correct ({accuracy:.1%})")
    print(f"  Positive: {class_correct['positive']}/{class_total['positive']}")
    print(f"  Negative: {class_correct['negative']}/{class_total['negative']}")
    print(f"  Neutral:  {class_correct['neutral']}/{class_total['neutral']}")

    # Print misclassifications for the agent to study
    misses = []
    for item in golden_set:
        predicted = classify(item["text"])
        if predicted != item["label"]:
            misses.append(
                f"  [{item['label']}→{predicted}] \"{item['text'][:60]}\""
            )

    if misses:
        print(f"\nMisclassified ({len(misses)}):")
        for m in misses:
            print(m)

    # Floor assertion — prevent catastrophic regression
    assert accuracy > 0.2, f"Accuracy catastrophically low: {accuracy:.1%}"
