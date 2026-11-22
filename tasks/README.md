# Task Package Standard (`tasks/<task-id>/`)

Every benchmark task in `skill-eval` follows the exact same isolated plug-in layout:

```text
tasks/<task-id>/
├── task.yaml           # Metadata, Jev atomic checklist items, optional visual_items
├── prompt.md           # Base prompt identical across A, B, and C2 (C1 adds 1-line prefix)
├── starter/            # Clean baseline files copied into /workspace inside Docker
├── grader/
│   └── grade.py        # Exposes `grade(run_id, workspace, deliverables, task_dir) -> GradeResult`
├── reference/
│   ├── gold/           # Reference solution that MUST score >= 9.5/10 and pass all 3 gates
│   └── negative-cases/ # >= 2 plausible buggy/shortcut solutions that MUST fail specific gates
└── anchors/            # Good & flawed examples for pre-freeze Jev calibration (>=0.80, 100% agree)
```

Phase 2 will populate all 8 tasks (`G1`–`G8`) under this contract and verify every task against its gold & negative reference cases before running the 32-run `calibration-v1` ceiling gate.
