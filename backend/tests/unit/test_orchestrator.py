"""Unit tests for the pipeline orchestrator routing — agents are mocked, so these
run without AWS/Bedrock/DB and exercise run_turn's outcomes directly.

Flow under test: a normal message hits Requirements (front door); if intake
completes, the spec is handed to the Architect; Executor runs on confirmation."""
from unittest.mock import patch

from pipeline.orchestrator import run_turn, stream_turn
from pipeline.state import PipelineState


def _state(**kw):
    base = dict(user_id="u1", session_id="s1", user_message="hi")
    base.update(kw)
    return PipelineState(**base)


def _req(text="next question?", spec=None, messages=None):
    return {"text": text, "spec": spec, "messages": messages if messages is not None else [{"role": "assistant"}]}


def _arch(text="here's the plan", plan=None, messages=None):
    return {"text": text, "plan": plan, "messages": messages if messages is not None else [{"role": "assistant"}]}


def test_question_stays_in_requirements_as_conversation():
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="You have 2 buckets.")) as m_req, \
         patch("pipeline.orchestrator.run_architect") as m_arch:
        state = run_turn(_state(user_message="show my buckets"))

    assert state.outcome == "conversation"
    assert state.display_text == "You have 2 buckets."
    assert state.requirements_complete is False
    m_req.assert_called_once()
    m_arch.assert_not_called()


def test_incomplete_intake_returns_next_question():
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="Which region?")), \
         patch("pipeline.orchestrator.run_architect") as m_arch:
        state = run_turn(_state(user_message="build me an app"))

    assert state.outcome == "conversation"
    assert state.display_text == "Which region?"
    m_arch.assert_not_called()


_NO_CRITIQUE = {"blocking_issues": [], "suggestions": []}


def test_completed_intake_hands_spec_to_architect_and_proposes_plan():
    spec = {"intent": "a website", "scale": "small"}
    plan = {"plan": [{"action": "create", "resource_type": "s3_bucket", "config": {}}]}
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(spec=spec)), \
         patch("pipeline.orchestrator.run_architect", return_value=_arch(plan=plan)) as m_arch, \
         patch("pipeline.orchestrator.run_critic", return_value=_NO_CRITIQUE):
        state = run_turn(_state(user_message="last answer"))

    assert state.requirements_complete is True
    assert state.requirements_spec == spec
    assert state.outcome == "plan_proposed"
    assert state.pending_plan is state.plan
    assert state.awaiting_confirmation is True
    # validation attaches a real cost estimate to the plan
    assert "estimated_monthly_cost" in state.plan
    # the architect must be handed the finalized spec, not the raw user message
    handoff_arg = m_arch.call_args.args[0]
    assert "a website" in handoff_arg


def test_completed_intake_with_destructive_plan_is_flagged():
    spec = {"intent": "remove old bucket"}
    plan = {"plan": [{"action": "delete", "resource_type": "s3_bucket", "resource_id": "b"}]}
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(spec=spec)), \
         patch("pipeline.orchestrator.run_architect", return_value=_arch(plan=plan)), \
         patch("pipeline.orchestrator.run_critic", return_value=_NO_CRITIQUE):
        state = run_turn(_state())
    assert state.plan_is_destructive is True


def test_tier1_loop_refines_an_invalid_plan():
    """A free-tier-violating plan is sent back to the architect, which returns a
    corrected one; the loop then converges."""
    spec = {"intent": "a cache"}
    bad = {"plan": [{"action": "create", "resource_type": "rds_instance", "config": {}}]}   # not free-tier
    good = {"plan": [{"action": "create", "resource_type": "s3_bucket", "config": {}}]}
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(spec=spec)), \
         patch("pipeline.orchestrator.run_architect", side_effect=[_arch(plan=bad), _arch(plan=good)]) as m_arch, \
         patch("pipeline.orchestrator.run_critic", return_value=_NO_CRITIQUE):
        state = run_turn(_state(free_tier_mode=True))

    assert m_arch.call_count == 2            # initial + one refinement round
    assert state.validation_rounds >= 1
    assert state.validation_blocking == []    # converged clean
    assert state.plan["plan"][0]["resource_type"] == "s3_bucket"
    assert state.outcome == "plan_proposed"


def test_critic_findings_are_surfaced_not_looped():
    spec = {"intent": "a server"}
    plan = {"plan": [{"action": "create", "resource_type": "s3_bucket", "config": {}}]}
    critique = {"blocking_issues": ["bucket is public"], "suggestions": ["enable versioning"]}
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(spec=spec)), \
         patch("pipeline.orchestrator.run_architect", return_value=_arch(plan=plan)) as m_arch, \
         patch("pipeline.orchestrator.run_critic", return_value=critique):
        state = run_turn(_state())

    # critic does NOT trigger another architect round — surfaced for the user gate
    assert m_arch.call_count == 1
    assert state.validation_blocking == ["bucket is public"]
    assert state.validation_suggestions == ["enable versioning"]
    assert state.outcome == "plan_proposed"


def test_confirm_yes_executes_and_clears_gate():
    plan = {"plan": [{"action": "create", "resource_type": "s3_bucket", "config": {"Bucket": "x"}}]}
    exec_result = {"text": "Created bucket.", "results": [{"success": True, "resource_id": "x"}]}
    with patch("pipeline.orchestrator.run_executor", return_value=exec_result) as m_exec, \
         patch("pipeline.orchestrator.generate_files", return_value={"readme.md": "hi"}) as m_files, \
         patch("pipeline.orchestrator.run_validator", return_value=[{"resource_id": "x", "healthy": True}]) as m_val, \
         patch("pipeline.orchestrator.run_summary", return_value="All set — your bucket is live!") as m_sum:
        state = run_turn(_state(confirm=True, pending_plan=plan, plan_is_destructive=False))

    assert state.outcome == "executed"
    assert state.execution_results == exec_result["results"]
    assert state.generated_files == {"readme.md": "hi"}
    assert state.plan == plan                 # executed plan preserved for the deployment record
    assert state.health == [{"resource_id": "x", "healthy": True}]
    assert state.display_text == "All set — your bucket is live!"  # summary replaces raw executor text
    assert state.pending_plan is None         # gate cleared
    assert state.awaiting_confirmation is False
    m_exec.assert_called_once()
    assert m_exec.call_args.kwargs["use_cloud_control"] is True   # generic breadth enabled
    m_files.assert_called_once()
    m_val.assert_called_once()
    m_sum.assert_called_once()


def test_executed_summary_falls_back_to_executor_text_when_summary_empty():
    plan = {"plan": [{"action": "create", "resource_type": "s3_bucket", "config": {"Bucket": "x"}}]}
    exec_result = {"text": "Created bucket.", "results": [{"success": True, "resource_id": "x"}]}
    with patch("pipeline.orchestrator.run_executor", return_value=exec_result), \
         patch("pipeline.orchestrator.generate_files", return_value={}), \
         patch("pipeline.orchestrator.run_validator", return_value=[]), \
         patch("pipeline.orchestrator.run_summary", return_value=""):
        state = run_turn(_state(confirm=True, pending_plan=plan))
    assert state.display_text == "Created bucket."


# --- streaming (LangGraph graph.stream) -----------------------------------------


def _drain(events):
    progress = [e for e in events if e["type"] == "progress"]
    final = next(e for e in events if e["type"] == "final")
    return [p["stage"] for p in progress], final["state"]


def test_stream_turn_emits_progress_per_node_then_final():
    spec = {"intent": "a website", "scale": "small"}
    plan = {"plan": [{"action": "create", "resource_type": "s3_bucket", "config": {}}]}
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(spec=spec)), \
         patch("pipeline.orchestrator.run_architect", return_value=_arch(plan=plan)), \
         patch("pipeline.orchestrator.run_critic", return_value=_NO_CRITIQUE):
        stages, final = _drain(list(stream_turn(_state(user_message="last answer"))))

    # each agent surfaced as its own live progress event, in order
    assert stages == ["requirements", "architect", "validate", "finalize"]
    assert final.outcome == "plan_proposed"
    assert "estimated_monthly_cost" in final.plan   # final state fully rebuilt from the stream


def test_stream_turn_surfaces_the_refinement_cycle_live():
    spec = {"intent": "a cache"}
    bad = {"plan": [{"action": "create", "resource_type": "rds_instance", "config": {}}]}   # not free-tier
    good = {"plan": [{"action": "create", "resource_type": "s3_bucket", "config": {}}]}
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(spec=spec)), \
         patch("pipeline.orchestrator.run_architect", side_effect=[_arch(plan=bad), _arch(plan=good)]), \
         patch("pipeline.orchestrator.run_critic", return_value=_NO_CRITIQUE):
        stages, final = _drain(list(stream_turn(_state(free_tier_mode=True))))

    # the validate -> architect cycle shows up as a second architect + validate pass
    assert stages == ["requirements", "architect", "validate", "architect", "validate", "finalize"]
    assert final.plan["plan"][0]["resource_type"] == "s3_bucket"


def test_stream_turn_conversation_stops_after_requirements():
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="Which region?")), \
         patch("pipeline.orchestrator.run_architect") as m_arch:
        stages, final = _drain(list(stream_turn(_state(user_message="build me an app"))))

    assert stages == ["requirements"]          # graph ended right after the front door
    assert final.outcome == "conversation"
    assert final.display_text == "Which region?"
    m_arch.assert_not_called()


def test_stream_turn_confirm_yes_streams_executor():
    plan = {"plan": [{"action": "create", "resource_type": "s3_bucket", "config": {"Bucket": "x"}}]}
    exec_result = {"text": "done", "results": [{"success": True, "resource_id": "x"}]}
    with patch("pipeline.orchestrator.run_executor", return_value=exec_result), \
         patch("pipeline.orchestrator.generate_files", return_value={}), \
         patch("pipeline.orchestrator.run_validator", return_value=[]), \
         patch("pipeline.orchestrator.run_summary", return_value="All set!"):
        stages, final = _drain(list(stream_turn(_state(confirm=True, pending_plan=plan))))

    assert stages == ["executor"]
    assert final.outcome == "executed"
    assert final.display_text == "All set!"


def test_confirm_no_cancels_without_executing():
    plan = {"plan": [{"action": "delete", "resource_type": "ec2_instance", "resource_id": "i-1"}]}
    with patch("pipeline.orchestrator.run_executor") as m_exec:
        state = run_turn(_state(confirm=False, pending_plan=plan, plan_is_destructive=True))

    assert state.outcome == "cancelled"
    assert "cancelled" in state.display_text.lower()
    assert state.pending_plan is None
    assert state.plan_is_destructive is False
    m_exec.assert_not_called()


def test_confirm_without_a_pending_plan_falls_through_to_requirements():
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="sure")) as m_req, \
         patch("pipeline.orchestrator.run_executor") as m_exec:
        state = run_turn(_state(user_message="yes", confirm=True, pending_plan=None))

    assert state.outcome == "conversation"
    m_req.assert_called_once()
    m_exec.assert_not_called()
