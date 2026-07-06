"""Summary agent (LLM mocked)."""
from unittest.mock import patch

from agents import summary


def test_summary_returns_stripped_model_text():
    with patch("agents.summary.run_completion", return_value="  Your bucket is ready!  "):
        out = summary.run_summary({"plan": []}, [{"success": True}], [])
    assert out == "Your bucket is ready!"


def test_summary_returns_empty_when_model_unavailable():
    with patch("agents.summary.run_completion", side_effect=RuntimeError("down")):
        out = summary.run_summary({"plan": []}, [], [])
    assert out == ""  # caller falls back to the executor's own text
