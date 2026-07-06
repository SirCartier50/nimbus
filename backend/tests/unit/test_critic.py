"""Tier-2 critic (LLM mocked)."""
from unittest.mock import patch

from agents import critic


def test_parse_json_tolerates_fences_and_prose():
    text = 'Here is my review:\n```json\n{"blocking_issues": ["a"], "suggestions": []}\n```\nthanks'
    assert critic._parse_json(text) == {"blocking_issues": ["a"], "suggestions": []}


def test_run_critic_returns_parsed_lists():
    payload = '{"blocking_issues": ["SG open to the world on port 22"], "suggestions": ["use gp3"]}'
    with patch("agents.critic.run_completion", return_value=payload):
        out = critic.run_critic({"intent": "x"}, {"plan": []})
    assert out["blocking_issues"] == ["SG open to the world on port 22"]
    assert out["suggestions"] == ["use gp3"]


def test_run_critic_coerces_non_strings_and_drops_empties():
    payload = '{"blocking_issues": [123, "", "real"], "suggestions": []}'
    with patch("agents.critic.run_completion", return_value=payload):
        out = critic.run_critic({}, {})
    assert out["blocking_issues"] == ["123", "real"]


def test_run_critic_degrades_to_empty_on_bad_json():
    with patch("agents.critic.run_completion", return_value="the plan looks fine to me!"):
        out = critic.run_critic({}, {})
    assert out == {"blocking_issues": [], "suggestions": []}


def test_run_critic_degrades_to_empty_when_model_raises():
    with patch("agents.critic.run_completion", side_effect=RuntimeError("bedrock down")):
        out = critic.run_critic({}, {})
    assert out == {"blocking_issues": [], "suggestions": []}
