import json
from pathlib import Path

from .models import MouthQualitySignals, OralVideoTask


def mouth_quality_artifacts_for(video_path: Path) -> tuple[Path, Path]:
    return video_path.with_suffix(".mouth_state.json"), video_path.with_suffix(".mouth_diagnosis.json")


def collect_mouth_quality_signals(video_path: Path) -> MouthQualitySignals | None:
    mouth_state_path, diagnosis_path = mouth_quality_artifacts_for(video_path)
    if not mouth_state_path.exists() and not diagnosis_path.exists():
        return None
    diagnosis = {}
    if diagnosis_path.exists():
        try:
            diagnosis = json.loads(diagnosis_path.read_text(encoding="utf-8"))
        except Exception as exc:
            diagnosis = {"verdict": "diagnostics_unreadable", "error": str(exc)}
    alignment = diagnosis.get("mouth_state_alignment") if isinstance(diagnosis, dict) else None
    if not isinstance(alignment, dict):
        alignment = {}
    return MouthQualitySignals(
        mouth_state_path=str(mouth_state_path) if mouth_state_path.exists() else None,
        mouth_diagnosis_path=str(diagnosis_path) if diagnosis_path.exists() else None,
        verdict=diagnosis.get("verdict") if isinstance(diagnosis, dict) else None,
        mouth_state_alignment_verdict=alignment.get("verdict"),
        low_energy_visible_gap_ratio=diagnosis.get("low_energy_visible_gap_ratio") if isinstance(diagnosis, dict) else None,
        high_energy_muted_open_ratio=diagnosis.get("high_energy_muted_open_ratio") if isinstance(diagnosis, dict) else None,
        high_energy_mean_ratio=diagnosis.get("high_energy_mean_ratio") if isinstance(diagnosis, dict) else None,
        vowel_muted_ratio=alignment.get("vowel_muted_ratio"),
        vowel_mean_ratio=alignment.get("vowel_mean_ratio"),
    )


def _quality_metric(value: float | None, fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def mouth_quality_score(quality: MouthQualitySignals | None) -> tuple[int, str]:
    if quality is None:
        return 0, "missing"
    score = 100.0
    score -= min(_quality_metric(quality.low_energy_visible_gap_ratio) * 100.0, 100.0) * 0.45
    score -= min(_quality_metric(quality.high_energy_muted_open_ratio) * 100.0, 100.0) * 0.30
    score -= min(_quality_metric(quality.vowel_muted_ratio) * 100.0, 100.0) * 0.20
    if quality.verdict and quality.verdict != "ok":
        score -= 20.0
    if quality.mouth_state_alignment_verdict and quality.mouth_state_alignment_verdict != "ok":
        score -= 15.0
    if quality.high_energy_mean_ratio is not None and quality.high_energy_mean_ratio < 0.24:
        score -= min((0.24 - quality.high_energy_mean_ratio) * 120.0, 18.0)
    if quality.vowel_mean_ratio is not None and quality.vowel_mean_ratio < 0.24:
        score -= min((0.24 - quality.vowel_mean_ratio) * 100.0, 15.0)
    score = int(round(max(0.0, min(score, 100.0))))
    if score >= 86 and quality.verdict == "ok" and (quality.mouth_state_alignment_verdict in {None, "ok"}):
        return score, "ok"
    if score >= 70:
        return score, "watch"
    return score, "needs_review"


def mouth_quality_issues(quality: MouthQualitySignals | None) -> list[dict]:
    if quality is None:
        return [
            {
                "code": "missing_quality",
                "severity": "info",
                "metric": None,
                "value": None,
                "hint": "run_internal_mouth_quality_diagnostics",
            }
        ]

    issues: list[dict] = []
    if quality.verdict and quality.verdict not in {"ok", "diagnostics_unavailable"}:
        issues.append({
            "code": "overall_diagnosis_review",
            "severity": "warning",
            "metric": "verdict",
            "value": quality.verdict,
            "hint": "inspect_mouth_quality_artifacts",
        })
    if quality.verdict == "diagnostics_unavailable":
        issues.append({
            "code": "diagnostics_unavailable",
            "severity": "warning",
            "metric": "verdict",
            "value": quality.verdict,
            "hint": "inspect_diagnostics_pipeline",
        })
    if quality.mouth_state_alignment_verdict and quality.mouth_state_alignment_verdict != "ok":
        issues.append({
            "code": "mouth_state_alignment_review",
            "severity": "warning",
            "metric": "mouth_state_alignment_verdict",
            "value": quality.mouth_state_alignment_verdict,
            "hint": "inspect_audio_mouth_state_mapping",
        })
    if _quality_metric(quality.low_energy_visible_gap_ratio) > 0.20:
        issues.append({
            "code": "closed_state_visible_gap",
            "severity": "high",
            "metric": "low_energy_visible_gap_ratio",
            "value": quality.low_energy_visible_gap_ratio,
            "hint": "strengthen_closed_state_control",
        })
    if _quality_metric(quality.high_energy_muted_open_ratio) > 0.35:
        issues.append({
            "code": "high_energy_muted_open",
            "severity": "high",
            "metric": "high_energy_muted_open_ratio",
            "value": quality.high_energy_muted_open_ratio,
            "hint": "increase_high_energy_open_release",
        })
    if _quality_metric(quality.vowel_muted_ratio) > 0.35:
        issues.append({
            "code": "expected_vowel_muted",
            "severity": "high",
            "metric": "vowel_muted_ratio",
            "value": quality.vowel_muted_ratio,
            "hint": "increase_vowel_release_floor",
        })
    if quality.high_energy_mean_ratio is not None and quality.high_energy_mean_ratio < 0.24:
        issues.append({
            "code": "high_energy_mean_low",
            "severity": "warning",
            "metric": "high_energy_mean_ratio",
            "value": quality.high_energy_mean_ratio,
            "hint": "inspect_open_range_mapping",
        })
    if quality.vowel_mean_ratio is not None and quality.vowel_mean_ratio < 0.24:
        issues.append({
            "code": "vowel_mean_low",
            "severity": "warning",
            "metric": "vowel_mean_ratio",
            "value": quality.vowel_mean_ratio,
            "hint": "inspect_vowel_release_mapping",
        })
    return issues


def build_mouth_quality_report(tasks: list[OralVideoTask], *, include_missing: bool = True) -> dict:
    items = []
    scores = []
    metric_values: dict[str, list[float]] = {
        "low_energy_visible_gap_ratio": [],
        "high_energy_muted_open_ratio": [],
        "high_energy_mean_ratio": [],
        "vowel_muted_ratio": [],
        "vowel_mean_ratio": [],
    }
    grade_counts = {"ok": 0, "watch": 0, "needs_review": 0, "missing": 0}
    issue_counts: dict[str, int] = {}
    hint_counts: dict[str, int] = {}
    for task in reversed(tasks):
        score, grade = mouth_quality_score(task.mouth_quality)
        issues = mouth_quality_issues(task.mouth_quality)
        grade_counts[grade] = grade_counts.get(grade, 0) + 1
        for issue in issues:
            code = str(issue.get("code") or "unknown")
            hint = str(issue.get("hint") or "none")
            issue_counts[code] = issue_counts.get(code, 0) + 1
            hint_counts[hint] = hint_counts.get(hint, 0) + 1
        if task.mouth_quality is not None:
            scores.append(score)
            for metric in metric_values:
                value = getattr(task.mouth_quality, metric)
                if value is not None:
                    metric_values[metric].append(float(value))
        if include_missing or task.mouth_quality is not None:
            items.append({
                "task_id": task.task_id,
                "title": task.title,
                "status": task.status,
                "output_video_path": task.output_video_path,
                "score": score,
                "grade": grade,
                "issues": issues,
                "quality": task.mouth_quality.model_dump(mode="json") if task.mouth_quality else None,
            })
    metric_means = {
        metric: (round(sum(values) / len(values), 4) if values else None)
        for metric, values in metric_values.items()
    }
    return {
        "summary": {
            "total_tasks": len(tasks),
            "with_mouth_quality": len(scores),
            "missing_mouth_quality": grade_counts.get("missing", 0),
            "average_score": round(sum(scores) / len(scores), 1) if scores else None,
            "grade_counts": grade_counts,
            "issue_counts": issue_counts,
            "hint_counts": hint_counts,
            "metric_means": metric_means,
        },
        "items": items,
    }
