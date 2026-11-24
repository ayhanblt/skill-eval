"""Single-source-of-truth Pydantic schemas for every stage of the pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Condition = Literal["A", "B", "C1", "C2"]
Archetype = Literal[
    "tool_craft",
    "workflow_discipline",
    "production_engineering",
    "proprietary_custom",
]
ErrorClass = Literal[
    "infra_sandbox",
    "expected_negative",
    "recoverable_agent_error",
    "repeated_or_unverified_error",
]
ExposureLevel = Literal[
    "none",
    "metadata_only",
    "invoked_wrong_distractor",
    "invoked_target",
    "references_read",
    "preloaded",
]
AdherenceState = Literal["applied", "not_applied", "violated", "not_applicable"]
RunStatus = Literal[
    "pending",
    "completed",
    "budget_exhausted",
    "timeout",
    "infra_error",
    "quota_paused",
]


class TokenUsage(BaseModel):
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0


class MatrixRow(BaseModel):
    run_id: str
    study_id: str
    phase: Literal["calibration", "main"]
    task_id: str
    archetype: Archetype
    target_skill: str
    condition: Condition
    model: str
    repeat: int
    installed_skills: list[str] = Field(default_factory=list)
    preload_skill: str | None = None
    max_turns: int = 45
    timeout_seconds: int = 900


class FreezeLock(BaseModel):
    schema_version: int = 1
    study_id: str
    created_utc: datetime
    seed: int
    docker_image: str
    docker_image_id: str | None = None
    claude_cli_version: str
    judge_model: str
    file_hashes: dict[str, str]
    matrix: list[MatrixRow]


class RunManifest(BaseModel):
    schema_version: int = 1
    run_id: str
    study_id: str
    attempt_id: str
    row: MatrixRow
    status: RunStatus
    started_utc: datetime
    ended_utc: datetime | None = None
    agent_seconds: float | None = None
    grader_seconds: float | None = None
    exit_code: int | None = None
    terminal_subtype: str | None = None
    actual_models: list[str] = Field(default_factory=list)
    effort_requested: str = "medium"
    docker_image_id: str | None = None
    claude_cli_version: str | None = None
    prompt_sha256: str | None = None
    preload_sha256: str | None = None
    tokens: TokenUsage | None = None
    api_equivalent_cost_usd: float | None = None
    subscription_billed: bool = True
    failure_reason: str | None = None
    capture_files: list[str] = Field(default_factory=list)


class CheckOutcome(BaseModel):
    id: str
    dimension: Literal[
        "correctness_completeness",
        "robustness_edge_cases",
        "test_tdd_quality",
        "code_output_maintainability",
        "solution_performance_security",
    ]
    critical: bool = False
    passed: bool | None = None
    score_fraction: float | None = None  # 0.0..1.0 when partial credit applies
    detail: str = ""


class GateResults(BaseModel):
    G1_CONTRACT_BUILD: bool | None = None
    G2_CRITICAL_CORRECTNESS: bool | None = None
    G3_CRITICAL_SAFETY_RULES: bool | None = None

    @property
    def all_passed(self) -> bool:
        return (
            self.G1_CONTRACT_BUILD is True
            and self.G2_CRITICAL_CORRECTNESS is True
            and self.G3_CRITICAL_SAFETY_RULES is True
        )

    @property
    def any_failed(self) -> bool:
        return (
            self.G1_CONTRACT_BUILD is False
            or self.G2_CRITICAL_CORRECTNESS is False
            or self.G3_CRITICAL_SAFETY_RULES is False
        )


class GradeResult(BaseModel):
    schema_version: int = 1
    run_id: str
    task_id: str
    status: Literal["graded", "missing_deliverable", "grader_error"] = "graded"
    grader_seconds: float = 0.0
    gates: GateResults = Field(default_factory=GateResults)
    checks: list[CheckOutcome] = Field(default_factory=list)
    solution_performance: dict[str, Any] = Field(default_factory=dict)
    visual_previews: list[str] = Field(default_factory=list)
    error_detail: str | None = None


class ToolErrorEvent(BaseModel):
    event_index: int
    tool_name: str
    tool_use_id: str | None = None
    error_class: ErrorClass
    chained_with_previous: bool = False
    recovered_within_steps: int | None = None
    summary: str


class ProbeOutcome(BaseModel):
    probe_id: str
    description: str
    state: AdherenceState
    evidence: str = ""


class TraceSummary(BaseModel):
    schema_version: int = 1
    run_id: str
    total_turns: int = 0
    total_tool_calls: int = 0
    tool_call_counts: dict[str, int] = Field(default_factory=dict)

    # Error taxonomy (raw + collapsed non-chained episodes)
    raw_tool_errors: int = 0
    error_events: list[ToolErrorEvent] = Field(default_factory=list)
    error_counts_by_class: dict[ErrorClass, int] = Field(
        default_factory=lambda: {
            "infra_sandbox": 0,
            "expected_negative": 0,
            "recoverable_agent_error": 0,
            "repeated_or_unverified_error": 0,
        }
    )

    # Anti-"bodozlama dalma" process discipline metrics
    read_steps_before_first_edit: int = 0
    first_edit_turn: int | None = None
    total_edit_calls: int = 0
    unique_files_edited: int = 0
    rework_churn_ratio: float = 0.0  # (total_edits - unique_files) / max(1, total_edits)
    self_verified_after_last_edit: bool = False
    tdd_red_before_green: bool | None = None

    # 3-layer skill exposure & adherence
    skill_exposure: ExposureLevel = "none"
    invoked_skills: list[str] = Field(default_factory=list)
    wrong_distractor_skills_invoked: list[str] = Field(default_factory=list)
    reference_files_read: list[str] = Field(default_factory=list)
    probe_outcomes: list[ProbeOutcome] = Field(default_factory=list)


class JudgePassAnswer(BaseModel):
    pass_number: int
    choice: str | None = None
    confidence: float | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)


class JudgeItemResult(BaseModel):
    item_id: str
    dimension: Literal[
        "code_output_maintainability",
        "solution_performance_security",
        "visual_design",
    ] = "code_output_maintainability"
    question: str
    value: Literal["pass", "partial", "fail"] | None = None
    score_fraction: float | None = None  # pass=1.0, partial=0.5, fail=0.0
    source: Literal["jev", "jev_prob", "human_blind"] | None = None
    needs_human_review: bool = False
    passes: list[JudgePassAnswer] = Field(default_factory=list)
    human_note: str | None = None


class JudgeResult(BaseModel):
    schema_version: int = 1
    run_id: str
    blind_code: str
    judge_model: str
    items: list[JudgeItemResult] = Field(default_factory=list)
    visual_items: list[JudgeItemResult] = Field(default_factory=list)
    complete: bool = False


class DimensionScore(BaseModel):
    dimension: str
    weight: float
    earned: float | None = None
    fraction: float | None = None
    evidence_count: int = 0


class ScoreCard(BaseModel):
    schema_version: int = 1
    run_id: str
    study_id: str
    task_id: str
    archetype: Archetype
    condition: Condition
    model: str
    repeat: int
    status: RunStatus

    # Gated 0-10 Product Score
    gates: GateResults
    raw_product_score: float | None = None
    product_score: float | None = None  # capped <= 5.0 when any gate fails
    gate_capped: bool = False
    passed: bool | None = None  # True iff all gates pass AND product_score >= 7.0
    dimensions: list[DimensionScore] = Field(default_factory=list)

    # Separate 0-10 Process & Recovery Score
    process_score: float | None = None
    process_deductions: dict[str, float] = Field(default_factory=dict)

    # Efficiency & Cost Profile (not mixed into Product Score)
    agent_seconds: float | None = None
    grader_seconds: float | None = None
    tokens: TokenUsage | None = None
    api_equivalent_cost_usd: float | None = None

    # 3-Layer Skill Attribution
    skill_exposure: ExposureLevel = "none"
    adherence_rate: float | None = None  # applied / applicable probes
    adherence_applied: int = 0
    adherence_applicable: int = 0
    infra_error_count: int = 0
    agent_error_count: int = 0
    read_steps_before_first_edit: int = 0
    rework_churn_ratio: float = 0.0
    self_verified_after_last_edit: bool = False
