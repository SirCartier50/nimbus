"""Unit tests for the Requirements agent's parsing/handoff helpers and its
run_requirements wrapper (run_tool_loop mocked — no Bedrock)."""
import json
from unittest.mock import patch

from agents import requirements


def test_extract_spec_returns_none_without_block():
    text = "Which region are your users mostly in?"
    display, spec = requirements.extract_spec(text)
    assert display == text
    assert spec is None


def test_extract_spec_pulls_json_and_strips_tags():
    spec_obj = {"intent": "a website", "scale": "small", "budget_priority": "cost", "region": "us-east-1"}
    text = (
        "Great, I have everything I need!\n"
        f"<requirements-complete>\n{json.dumps(spec_obj)}\n</requirements-complete>"
    )
    display, spec = requirements.extract_spec(text)
    assert "<requirements-complete>" not in display
    assert display == "Great, I have everything I need!"
    assert spec == spec_obj


def test_extract_spec_malformed_json_strips_tags_instead_of_leaking_raw_text():
    """Regression: a less capable/instruction-following model (more likely on a
    non-Bedrock provider) can attempt the completion protocol with broken JSON
    inside it. The user must never see the raw tags/JSON fragment — that used to
    happen and looked like a confusing, broken response."""
    text = "done\n<requirements-complete>\n{not json\n</requirements-complete>"
    display, spec = requirements.extract_spec(text)
    assert spec is None
    assert "<requirements-complete>" not in display
    assert "{not json" not in display
    assert display == "done"


def test_extract_spec_malformed_json_with_no_surrounding_text_gets_a_friendly_fallback():
    text = "<requirements-complete>\n{not json\n</requirements-complete>"
    display, spec = requirements.extract_spec(text)
    assert spec is None
    assert "<requirements-complete>" not in display
    assert display == "Sorry, I had trouble with that — could you rephrase what you're looking to build?"


def test_build_spec_handoff_embeds_spec_json():
    spec = {"intent": "api backend", "runtime": "python"}
    handoff = requirements.build_spec_handoff(spec)
    assert "Produce the deployment plan now." in handoff
    assert json.loads(handoff[handoff.index("{"):handoff.rindex("}") + 1]) == spec


def test_run_requirements_question_mode_returns_no_spec():
    loop_result = {
        "text": "What kind of app are you building?",
        "messages": [{"role": "assistant", "content": [{"text": "What kind of app are you building?"}]}],
    }
    with patch("agents.requirements.run_tool_loop", return_value=loop_result):
        out = requirements.run_requirements("I want to build something", [])
    assert out["spec"] is None
    assert out["text"] == "What kind of app are you building?"


def test_run_requirements_complete_returns_spec_and_scrubs_tag_from_history():
    spec_obj = {"intent": "file storage", "scale": "small"}
    raw = f"All set!\n<requirements-complete>\n{json.dumps(spec_obj)}\n</requirements-complete>"
    loop_result = {
        "text": raw,
        "messages": [
            {"role": "user", "content": [{"text": "store files"}]},
            {"role": "assistant", "content": [{"text": raw}]},
        ],
    }
    with patch("agents.requirements.run_tool_loop", return_value=loop_result):
        out = requirements.run_requirements("store files", [])

    assert out["spec"] == spec_obj
    assert out["text"] == "All set!"
    # the control tag must not linger in the persisted assistant message
    last = out["messages"][-1]
    assert last["role"] == "assistant"
    assert "<requirements-complete>" not in last["content"][0]["text"]
    assert last["content"][0]["text"] == "All set!"
