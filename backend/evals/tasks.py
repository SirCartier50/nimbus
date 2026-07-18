"""Eval tasks + scorers for the Architect's planning.

Each task is a plain-English request plus a set of deterministic scorers that
inspect the produced plan. Scorers never call a model — they're pure functions
over (plan, tier1_issues), so the eval *logic* is unit-testable offline and the
only nondeterminism is the model call the runner makes.

A scorer returns (label, passed, detail). `run_scorers` applies all of a task's
scorers to one produced plan.
"""
from dataclasses import dataclass, field
from typing import Callable

from pipeline.validation import _FREE_TIER_DISALLOWED

# A scorer: (plan_or_None, tier1_issues) -> (label, passed, detail)
Scorer = Callable[[object, list], tuple]


# ---------------------------------------------------------------------------
# Plan helpers
# ---------------------------------------------------------------------------

def _create_steps(plan) -> list:
    if not plan or not isinstance(plan.get("plan"), list):
        return []
    return [s for s in plan["plan"] if isinstance(s, dict) and s.get("action") == "create"]


def resource_types(plan) -> list:
    return [s.get("resource_type") for s in _create_steps(plan)]


def is_generic(rt) -> bool:
    """A CloudFormation type name (AWS::Service::Resource) = the generic path."""
    return isinstance(rt, str) and "::" in rt


# Match a logical resource whether the model emitted the curated short name or the
# equivalent CloudFormation type. `token` is matched case-insensitively against the
# CFN form (e.g. "::S3::Bucket").
def _match_kind(curated: str, cfn_token: str) -> Callable[[object], bool]:
    def pred(rt) -> bool:
        if rt == curated:
            return True
        return isinstance(rt, str) and cfn_token.lower() in rt.lower()

    return pred


S3 = _match_kind("s3_bucket", "::S3::Bucket")
VPC = _match_kind("vpc", "::EC2::VPC")
SUBNET = _match_kind("subnet", "::EC2::Subnet")
LAMBDA = _match_kind("lambda_function", "::Lambda::Function")
QUEUE = _match_kind("__none__", "::SQS::Queue")  # no curated tool exists for SQS


# ---------------------------------------------------------------------------
# Scorer factories
# ---------------------------------------------------------------------------

def produced_a_plan() -> Scorer:
    def s(plan, issues):
        ok = bool(plan and plan.get("plan"))
        return ("produced a plan", ok, "" if ok else "no <nimbus-plan> block or empty plan")
    return s


def validation_clean() -> Scorer:
    def s(plan, issues):
        ok = not issues
        return ("passes Tier-1 validation", ok, "" if ok else "; ".join(issues))
    return s


def includes(label: str, pred: Callable[[object], bool]) -> Scorer:
    def s(plan, issues):
        rts = resource_types(plan)
        matched = [rt for rt in rts if pred(rt)]
        ok = bool(matched)
        return (f"includes {label}", ok, f"matched {matched}" if ok else f"resource_types={rts}")
    return s


def at_least_n(label: str, pred: Callable[[object], bool], n: int) -> Scorer:
    def s(plan, issues):
        rts = resource_types(plan)
        count = sum(1 for rt in rts if pred(rt))
        ok = count >= n
        return (f"includes >={n} {label}", ok, f"found {count}")
    return s


def uses_generic_path() -> Scorer:
    """The Bitter-Lesson #4 signal: did the model drive the generic Cloud Control
    path (an AWS::… type) instead of leaning only on curated tools?"""
    def s(plan, issues):
        rts = resource_types(plan)
        generic = [rt for rt in rts if is_generic(rt)]
        ok = bool(generic)
        return ("uses the generic AWS::… path", ok, f"generic={generic}" if ok else f"only curated {rts}")
    return s


def excludes_paid_in_free_tier() -> Scorer:
    def s(plan, issues):
        paid = [rt for rt in resource_types(plan) if rt in _FREE_TIER_DISALLOWED]
        ok = not paid
        return ("no non-free-tier paid resource", ok, f"included {paid}" if paid else "")
    return s


# ---------------------------------------------------------------------------
# The task set
# ---------------------------------------------------------------------------

@dataclass
class EvalTask:
    id: str
    prompt: str
    free_tier: bool
    scorers: list = field(default_factory=list)
    # True = this task specifically probes the generic Cloud Control path. The
    # aggregate of these is the headline "can we lean on generic?" signal for #4.
    generic_probe: bool = False


TASKS: list[EvalTask] = [
    EvalTask(
        id="s3_uploads",
        prompt="Create an S3 bucket for storing user file uploads. Nothing else.",
        free_tier=True,
        scorers=[produced_a_plan(), validation_clean(), includes("an S3 bucket", S3)],
    ),
    EvalTask(
        id="sqs_queue",
        prompt="Set up a message queue to buffer background jobs between two services.",
        free_tier=False,
        generic_probe=True,  # SQS has NO curated tool — a correct plan MUST go generic
        scorers=[
            produced_a_plan(),
            validation_clean(),
            includes("an SQS queue", QUEUE),
            uses_generic_path(),
        ],
    ),
    EvalTask(
        id="vpc_subnets",
        prompt="Create a VPC with two subnets inside it.",
        free_tier=True,
        scorers=[
            produced_a_plan(),
            validation_clean(),  # also enforces vpc-before-subnet ordering
            includes("a VPC", VPC),
            at_least_n("subnets", SUBNET, 2),
        ],
    ),
    EvalTask(
        id="free_tier_guard",
        prompt="I want a large managed PostgreSQL database with 16 GB of RAM for production.",
        free_tier=True,  # the model should refuse/omit the paid RDS instance, not smuggle it in
        scorers=[produced_a_plan(), validation_clean(), excludes_paid_in_free_tier()],
    ),
    EvalTask(
        id="lambda_http",
        prompt="Deploy a serverless function that responds to HTTP requests.",
        free_tier=True,
        scorers=[produced_a_plan(), validation_clean(), includes("a Lambda function", LAMBDA)],
    ),
]


def run_scorers(task: EvalTask, plan, issues: list) -> list:
    """Apply every scorer for `task` to a produced plan. Returns a list of
    (label, passed, detail) tuples."""
    return [scorer(plan, issues) for scorer in task.scorers]
