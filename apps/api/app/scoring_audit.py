"""M11 scoring consistency audit — deliberately NOT a demographic bias audit.

This system collects no protected-characteristic data (race, gender, age,
disability, etc.) about candidates — appropriately, since collecting it
would itself be a significant legal/privacy decision this project has never
made. A disparate-impact analysis is therefore not implementable
responsibly here, and PLAN.md's "bias audit" line item is scoped down to
what actually is verifiable from the data this system has: is the
deterministic scoring pipeline behaving consistently with its own stated
guarantees? See ADR-023.

Three checks, all pure functions over already-persisted rows:
  - verdict drift: the same resume, scored twice with the same weight
    profile, landing on a different verdict (scoring.py promises byte-
    identical runs for identical inputs — this would mean that broke)
  - missing citations: a persisted dimension judgement with no cited
    evidence (the gateway contract requires at least one — this checks the
    promise actually held on the way into the database)
  - narrow score bands: a weight profile whose runs cluster in a
    suspiciously tight score range, which more often indicates the profile
    isn't discriminating between candidates than that every candidate is
    equally qualified
"""

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import pstdev


@dataclass(frozen=True)
class ScoringRunFacts:
    resume_id: str
    weight_profile_id: str
    total_score: int
    verdict: str
    run_fingerprint: str
    dimensions_payload: list[dict[str, object]]
    created_at: str


@dataclass
class AuditFinding:
    kind: str
    severity: str
    detail: str
    resume_ids: list[str] = field(default_factory=list)


NARROW_BAND_MIN_RUNS = 5
NARROW_BAND_STDEV_THRESHOLD = 3.0


def audit_verdict_drift(runs: list[ScoringRunFacts]) -> list[AuditFinding]:
    by_resume_and_profile: dict[tuple[str, str], list[ScoringRunFacts]] = defaultdict(list)
    for run in runs:
        by_resume_and_profile[(run.resume_id, run.weight_profile_id)].append(run)

    findings: list[AuditFinding] = []
    for (resume_id, _profile_id), group in by_resume_and_profile.items():
        verdicts = {run.verdict for run in group}
        if len(group) > 1 and len(verdicts) > 1:
            findings.append(
                AuditFinding(
                    kind="verdict_drift",
                    severity="high",
                    detail=(
                        f"Resume {resume_id} scored {len(group)} times against the same "
                        f"weight profile but landed on {len(verdicts)} different verdicts "
                        f"({sorted(verdicts)}) — scoring is supposed to be deterministic "
                        "for identical inputs."
                    ),
                    resume_ids=[resume_id],
                )
            )
    return findings


def audit_missing_citations(runs: list[ScoringRunFacts]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for run in runs:
        for dimension in run.dimensions_payload:
            refs = dimension.get("evidence_refs")
            if not refs:
                findings.append(
                    AuditFinding(
                        kind="missing_citation",
                        severity="high",
                        detail=(
                            f"Run {run.run_fingerprint[:16]} for resume {run.resume_id} has a "
                            f"'{dimension.get('dimension', 'unknown')}' judgement with no cited "
                            "evidence, violating the gateway contract."
                        ),
                        resume_ids=[run.resume_id],
                    )
                )
    return findings


def audit_narrow_score_bands(runs: list[ScoringRunFacts]) -> list[AuditFinding]:
    by_profile: dict[str, list[int]] = defaultdict(list)
    for run in runs:
        by_profile[run.weight_profile_id].append(run.total_score)

    findings: list[AuditFinding] = []
    for profile_id, scores in by_profile.items():
        if len(scores) < NARROW_BAND_MIN_RUNS:
            continue
        spread = pstdev(scores)
        if spread < NARROW_BAND_STDEV_THRESHOLD:
            findings.append(
                AuditFinding(
                    kind="narrow_score_band",
                    severity="medium",
                    detail=(
                        f"Weight profile {profile_id} produced {len(scores)} scores with a "
                        f"standard deviation of only {spread:.2f} points (range "
                        f"{min(scores)}-{max(scores)}) — the profile may not be "
                        "discriminating between candidates."
                    ),
                )
            )
    return findings


def run_audit(runs: list[ScoringRunFacts]) -> list[AuditFinding]:
    return [
        *audit_verdict_drift(runs),
        *audit_missing_citations(runs),
        *audit_narrow_score_bands(runs),
    ]


__all__ = [
    "NARROW_BAND_MIN_RUNS",
    "NARROW_BAND_STDEV_THRESHOLD",
    "AuditFinding",
    "ScoringRunFacts",
    "audit_missing_citations",
    "audit_narrow_score_bands",
    "audit_verdict_drift",
    "run_audit",
]
