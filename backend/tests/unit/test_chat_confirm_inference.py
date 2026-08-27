"""Unit tests for routes.chat._infer_confirm_from_text — the exact-match mapping
from a plain-English reply to a pending plan's Yes/No, so a user who types
"confirmed" or "launch" instead of clicking the button still triggers a real
confirm/cancel instead of the LLM hallucinating that it acted (observed live:
"Instance Launched" with nothing actually created)."""
from routes.chat import _infer_confirm_from_text


def test_common_affirmatives_map_to_true():
    for text in ["yes", "Yes", "confirmed", "CONFIRMED", "launch", "do it", "go ahead", "proceed", "deploy", "sure", "ok"]:
        assert _infer_confirm_from_text(text) is True, text


def test_common_negatives_map_to_false():
    for text in ["no", "No", "cancel", "cancelled", "stop", "nevermind", "not now", "abort"]:
        assert _infer_confirm_from_text(text) is False, text


def test_trailing_punctuation_and_whitespace_are_ignored():
    assert _infer_confirm_from_text("  confirmed!  ") is True
    assert _infer_confirm_from_text("cancel.") is False


def test_unrelated_free_text_is_not_matched():
    assert _infer_confirm_from_text("why did you have trouble") is None
    assert _infer_confirm_from_text("well?") is None
    assert _infer_confirm_from_text("first delete the t2 then launch the new one") is None


def test_substring_containing_a_keyword_does_not_match():
    # "launch" is an exact-match affirmative, but a question ABOUT launching
    # must never be misread as confirming a deploy.
    assert _infer_confirm_from_text("why did launch fail") is None
    assert _infer_confirm_from_text("launch it later, not now") is None
