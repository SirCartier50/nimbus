"""Offline coverage for the eval harness logic — no model, no AWS.

Verifies the scorers and the fake session, and that each task's scorers behave
as intended against a known-good and known-bad synthetic plan. This keeps the
eval *logic* honest in CI; the live model run (evals/run.py) is manual.
"""
from evals.fake_aws import FakeAWSSession
from evals.tasks import (
    TASKS,
    at_least_n,
    excludes_paid_in_free_tier,
    includes,
    is_generic,
    produced_a_plan,
    resource_types,
    run_scorers,
    uses_generic_path,
    validation_clean,
    S3,
    SUBNET,
    QUEUE,
    VPC,
)
from pipeline.validation import validate_plan


def _plan(*resource_types_):
    return {"plan": [
        {"step": i + 1, "action": "create", "resource_type": rt, "config": {}}
        for i, rt in enumerate(resource_types_)
    ]}


# ---- helpers -------------------------------------------------------------

def test_resource_types_and_is_generic():
    plan = _plan("s3_bucket", "AWS::SQS::Queue")
    assert resource_types(plan) == ["s3_bucket", "AWS::SQS::Queue"]
    assert is_generic("AWS::SQS::Queue") is True
    assert is_generic("s3_bucket") is False
    assert is_generic(None) is False


def test_match_kind_accepts_curated_or_cfn():
    assert S3("s3_bucket") and S3("AWS::S3::Bucket")
    assert not S3("vpc")
    assert VPC("vpc") and VPC("AWS::EC2::VPC")
    assert QUEUE("AWS::SQS::Queue") and not QUEUE("s3_bucket")


# ---- scorers -------------------------------------------------------------

def test_produced_a_plan():
    assert produced_a_plan()(_plan("s3_bucket"), [])[1] is True
    assert produced_a_plan()(None, [])[1] is False
    assert produced_a_plan()({"plan": []}, [])[1] is False


def test_validation_clean_reflects_issues():
    assert validation_clean()(_plan("s3_bucket"), [])[1] is True
    label, ok, detail = validation_clean()(_plan("s3_bucket"), ["boom"])
    assert ok is False and "boom" in detail


def test_includes_and_at_least_n():
    plan = _plan("vpc", "subnet", "subnet")
    assert includes("a VPC", VPC)(plan, [])[1] is True
    assert at_least_n("subnets", SUBNET, 2)(plan, [])[1] is True
    assert at_least_n("subnets", SUBNET, 3)(plan, [])[1] is False


def test_uses_generic_path():
    assert uses_generic_path()(_plan("AWS::SQS::Queue"), [])[1] is True
    assert uses_generic_path()(_plan("s3_bucket"), [])[1] is False


def test_excludes_paid_in_free_tier():
    assert excludes_paid_in_free_tier()(_plan("s3_bucket"), [])[1] is True
    assert excludes_paid_in_free_tier()(_plan("rds_instance"), [])[1] is False


# ---- task set end to end (synthetic plans, no model) ---------------------

def test_every_task_has_scorers_and_unique_ids():
    assert TASKS
    ids = [t.id for t in TASKS]
    assert len(ids) == len(set(ids))
    assert all(t.scorers for t in TASKS)


def test_sqs_task_passes_on_good_generic_plan_fails_on_curated_only():
    task = next(t for t in TASKS if t.id == "sqs_queue")
    good = _plan("AWS::SQS::Queue")
    good_scores = run_scorers(task, good, validate_plan(good, task.free_tier))
    assert all(ok for _, ok, _ in good_scores)

    # A plan that avoids the generic path can't satisfy the SQS task (no curated tool).
    bad = _plan("s3_bucket")
    bad_scores = run_scorers(task, bad, validate_plan(bad, task.free_tier))
    assert not all(ok for _, ok, _ in bad_scores)


def test_vpc_task_enforces_prereq_ordering_via_validation():
    task = next(t for t in TASKS if t.id == "vpc_subnets")
    # subnet before its prerequisite vpc -> Tier-1 validation flags it -> task fails
    misordered = {"plan": [
        {"step": 1, "action": "create", "resource_type": "subnet", "config": {}},
        {"step": 2, "action": "create", "resource_type": "vpc", "config": {}},
        {"step": 3, "action": "create", "resource_type": "subnet", "config": {}},
    ]}
    scores = run_scorers(task, misordered, validate_plan(misordered, task.free_tier))
    assert not all(ok for _, ok, _ in scores)


# ---- fake AWS session ----------------------------------------------------

def test_fake_session_is_hermetic():
    sess = FakeAWSSession()
    assert sess.region_name == "us-east-1"
    client = sess.client("sts", config=None)
    assert client.get_caller_identity()["Account"] == "000000000000"
    # arbitrary describe/list calls return an empty dict, never touching a network
    assert client.describe_instances() == {}
    assert client.list_buckets(Foo=1) == {}
