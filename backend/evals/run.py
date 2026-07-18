"""Run the Architect planning evals against a real LLM provider.

    cd backend
    python -m evals.run --provider openrouter
    python -m evals.run --provider groq --task sqs_queue --repeat 3
    python -m evals.run --provider openrouter --pref generic   # test the #4 flip

Uses a FakeAWSSession so nothing touches real AWS — this scores PLANNING only
(the architect turns a request into a validated plan); it does not deploy.
Provider keys are read from backend/.env (OPENROUTER_API_KEY, GROQ_API_KEY, …).
Per project policy, point this at FREE providers only.

Exit code is non-zero if any task fails, so it can gate CI or a model bump.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from agents.architect import run_architect  # noqa: E402 — after load_dotenv
from evals.fake_aws import FakeAWSSession  # noqa: E402
from evals.tasks import TASKS, run_scorers  # noqa: E402
from pipeline.validation import validate_plan  # noqa: E402


def _run_one(task, provider):
    """Run one task once: architect -> plan -> Tier-1 issues -> scorers."""
    started = time.time()
    try:
        result = run_architect(
            task.prompt, [], free_tier_mode=task.free_tier,
            aws_session=FakeAWSSession(), provider=provider,
        )
        plan = result.get("plan")
    except Exception as e:  # provider/network failure - record it, don't crash the run
        return {"error": str(e), "scores": [], "passed": False, "elapsed": round(time.time() - started, 1)}

    issues = validate_plan(plan, task.free_tier) if plan else ["no plan produced"]
    scores = run_scorers(task, plan, issues)
    passed = all(ok for _, ok, _ in scores)
    return {
        "error": None,
        "plan": plan,
        "scores": [{"label": lbl, "passed": ok, "detail": d} for lbl, ok, d in scores],
        "passed": passed,
        "elapsed": round(time.time() - started, 1),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Nimbus Architect planning evals")
    ap.add_argument("--provider", default=os.getenv("LLM_PROVIDER", "openrouter"),
                    help="LLM provider (openrouter | groq | huggingface). FREE providers only.")
    ap.add_argument("--task", action="append", help="Run only this task id (repeatable). Default: all.")
    ap.add_argument("--repeat", type=int, default=1, help="Runs per task (report worst-case pass).")
    ap.add_argument("--pref", help="Override ARCHITECT_RESOURCE_PREFERENCE for this run (curated|balanced|generic).")
    ap.add_argument("--out", help="Write the full JSON report to this path.")
    args = ap.parse_args(argv)

    if args.pref:
        os.environ["ARCHITECT_RESOURCE_PREFERENCE"] = args.pref

    tasks = [t for t in TASKS if not args.task or t.id in args.task]
    if not tasks:
        print(f"No tasks matched {args.task}. Known: {[t.id for t in TASKS]}", file=sys.stderr)
        return 2

    pref = os.getenv("ARCHITECT_RESOURCE_PREFERENCE", "curated")
    print(f"\nNimbus Architect evals - provider={args.provider}  preference={pref}  "
          f"repeat={args.repeat}\n" + "=" * 68)

    report = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider, "preference": pref, "repeat": args.repeat, "tasks": [],
    }
    total_pass = 0
    generic_probe_pass = generic_probe_total = 0

    for task in tasks:
        # Repeat and keep the WORST run — a model that only sometimes plans correctly
        # is not one to lean on. A task passes only if every repeat passed.
        runs = [_run_one(task, args.provider) for _ in range(args.repeat)]
        task_passed = all(r["passed"] for r in runs)
        worst = next((r for r in runs if not r["passed"]), runs[0])
        total_pass += int(task_passed)
        if task.generic_probe:
            generic_probe_total += 1
            generic_probe_pass += int(task_passed)

        mark = "PASS" if task_passed else "FAIL"
        print(f"\n[{mark}] {task.id}  ({worst['elapsed']}s)")
        if worst["error"]:
            print(f"       provider error: {worst['error']}")
        for sc in worst["scores"]:
            m = "  ok " if sc["passed"] else "  XX "
            detail = f"  - {sc['detail']}" if sc["detail"] and not sc["passed"] else ""
            print(f"     {m}{sc['label']}{detail}")

        report["tasks"].append({
            "id": task.id, "generic_probe": task.generic_probe,
            "passed": task_passed, "runs": runs,
        })

    print("\n" + "=" * 68)
    print(f"Overall: {total_pass}/{len(tasks)} tasks passed")
    if generic_probe_total:
        print(f"Generic-path capability (the #4 signal): "
              f"{generic_probe_pass}/{generic_probe_total} generic-probe tasks passed")
        print("  -> See evals/CHECKLIST.md for when this justifies flipping the preference to `generic`.")
    report["summary"] = {
        "tasks_passed": total_pass, "tasks_total": len(tasks),
        "generic_probe_passed": generic_probe_pass, "generic_probe_total": generic_probe_total,
    }

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nWrote report to {args.out}")

    return 0 if total_pass == len(tasks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
