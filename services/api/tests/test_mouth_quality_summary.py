import json

from app.models import MouthQualitySignals, OralVideoTask, TaskStatus
from app.mouth_quality import build_mouth_quality_report, mouth_quality_issues, mouth_quality_score
from tools.summarize_mouth_quality import load_tasks


def test_mouth_quality_score_grades_ok_and_needs_review():
    ok_score, ok_grade = mouth_quality_score(
        MouthQualitySignals(
            verdict="ok",
            mouth_state_alignment_verdict="ok",
            low_energy_visible_gap_ratio=0.0,
            high_energy_muted_open_ratio=0.0,
            high_energy_mean_ratio=0.2873,
            vowel_muted_ratio=0.1667,
            vowel_mean_ratio=0.2649,
        )
    )
    review_score, review_grade = mouth_quality_score(
        MouthQualitySignals(
            verdict="needs_review",
            mouth_state_alignment_verdict="needs_review",
            low_energy_visible_gap_ratio=0.35,
            high_energy_muted_open_ratio=0.5,
            high_energy_mean_ratio=0.21,
            vowel_muted_ratio=0.55,
            vowel_mean_ratio=0.22,
        )
    )

    assert ok_grade == "ok"
    assert ok_score >= 90
    assert review_grade == "needs_review"
    assert review_score < 70


def test_mouth_quality_issues_classify_internal_next_actions():
    missing = mouth_quality_issues(None)
    review = mouth_quality_issues(
        MouthQualitySignals(
            verdict="needs_review",
            mouth_state_alignment_verdict="needs_review",
            low_energy_visible_gap_ratio=0.35,
            high_energy_muted_open_ratio=0.5,
            high_energy_mean_ratio=0.21,
            vowel_muted_ratio=0.55,
            vowel_mean_ratio=0.22,
        )
    )
    ok = mouth_quality_issues(
        MouthQualitySignals(
            verdict="ok",
            mouth_state_alignment_verdict="ok",
            low_energy_visible_gap_ratio=0.0,
            high_energy_muted_open_ratio=0.0,
            high_energy_mean_ratio=0.2873,
            vowel_muted_ratio=0.1667,
            vowel_mean_ratio=0.2649,
        )
    )

    assert missing == [{
        "code": "missing_quality",
        "severity": "info",
        "metric": None,
        "value": None,
        "hint": "run_internal_mouth_quality_diagnostics",
    }]
    codes = {issue["code"] for issue in review}
    hints = {issue["hint"] for issue in review}
    assert {"closed_state_visible_gap", "high_energy_muted_open", "expected_vowel_muted"}.issubset(codes)
    assert {"strengthen_closed_state_control", "increase_vowel_release_floor"}.issubset(hints)
    assert ok == []


def test_build_mouth_quality_report_aggregates_task_metrics():
    tasks = [
        OralVideoTask(title="missing", status=TaskStatus.completed),
        OralVideoTask(
            title="ok",
            status=TaskStatus.completed,
            mouth_quality=MouthQualitySignals(
                verdict="ok",
                mouth_state_alignment_verdict="ok",
                low_energy_visible_gap_ratio=0.0,
                high_energy_muted_open_ratio=0.0,
                high_energy_mean_ratio=0.28,
                vowel_muted_ratio=0.1,
                vowel_mean_ratio=0.27,
            ),
        ),
    ]

    report = build_mouth_quality_report(tasks)

    assert report["summary"]["total_tasks"] == 2
    assert report["summary"]["with_mouth_quality"] == 1
    assert report["summary"]["missing_mouth_quality"] == 1
    assert report["summary"]["metric_means"]["vowel_muted_ratio"] == 0.1
    assert report["summary"]["issue_counts"]["missing_quality"] == 1
    assert report["summary"]["hint_counts"]["run_internal_mouth_quality_diagnostics"] == 1
    assert report["items"][0]["title"] == "ok"
    assert report["items"][0]["issues"] == []
    assert report["items"][1]["grade"] == "missing"
    assert report["items"][1]["issues"][0]["code"] == "missing_quality"

    quality_only = build_mouth_quality_report(tasks, include_missing=False)
    assert quality_only["summary"]["total_tasks"] == 2
    assert quality_only["summary"]["missing_mouth_quality"] == 1
    assert len(quality_only["items"]) == 1
    assert quality_only["items"][0]["title"] == "ok"


def test_summarize_mouth_quality_loads_tasks_json(tmp_path):
    task = OralVideoTask(
        title="json",
        status=TaskStatus.completed,
        mouth_quality=MouthQualitySignals(verdict="ok"),
    )
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(json.dumps([task.model_dump(mode="json")], ensure_ascii=False), encoding="utf-8")

    loaded = load_tasks(tasks_path)

    assert len(loaded) == 1
    assert loaded[0].title == "json"
    assert loaded[0].mouth_quality.verdict == "ok"
