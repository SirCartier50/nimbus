# backend/evals

A small, hermetic harness that scores the **Architect agent's planning** against
real tasks, so a new model is judged on evidence. It runs the architect with a
fake AWS session (no real AWS, no deploys, no spend) and applies deterministic
scorers to the plan it produces.

- `tasks.py` — the task set + pure scorers (unit-tested offline in
  `tests/unit/test_evals.py`).
- `fake_aws.py` — the hermetic boto3-Session stand-in.
- `run.py` — the CLI runner (needs a real provider key to call a model).
- `CHECKLIST.md` — **read this** when a new model drops: how to run it and when
  the results justify flipping `ARCHITECT_RESOURCE_PREFERENCE` toward `generic`.

Quick start:

```bash
cd backend
python -m evals.run --provider openrouter --repeat 3
```

`out/` (JSON reports) is gitignored.
