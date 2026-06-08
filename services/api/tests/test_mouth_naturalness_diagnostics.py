from tools.diagnose_mouth_naturalness import (
    MouthFrameMetric,
    summarize_atlas_coverage,
    summarize_mouth_metrics,
    summarize_mouth_state_alignment,
)


def test_mouth_naturalness_summary_reports_stable_ok_case():
    metrics = [
        MouthFrameMetric(index=0, ratio=0.07, dark_share=0.05, audio_energy=0.05),
        MouthFrameMetric(index=1, ratio=0.08, dark_share=0.05, audio_energy=0.10),
        MouthFrameMetric(index=2, ratio=0.10, dark_share=0.06, audio_energy=0.20),
        MouthFrameMetric(index=3, ratio=0.14, dark_share=0.06, audio_energy=0.40),
        MouthFrameMetric(index=4, ratio=0.20, dark_share=0.08, audio_energy=0.55),
        MouthFrameMetric(index=5, ratio=0.26, dark_share=0.08, audio_energy=0.72),
    ]

    summary = summarize_mouth_metrics(metrics, total_frames=6)

    assert summary["verdict"] == "ok"
    assert summary["detection_rate"] == 1.0
    assert summary["low_energy_closed_leak_ratio"] == 0.0
    assert summary["ratio"]["max"] == 0.26
    assert summary["audio_energy_correlation"] > 0.8


def test_mouth_naturalness_summary_flags_closed_mouth_drift_and_jitter():
    metrics = [
        MouthFrameMetric(index=0, ratio=0.24, dark_share=0.50, audio_energy=0.02, shadow_share=0.58),
        MouthFrameMetric(index=1, ratio=0.06, dark_share=0.45, audio_energy=0.03, shadow_share=0.52),
        MouthFrameMetric(index=2, ratio=0.28, dark_share=0.48, audio_energy=0.04, shadow_share=0.61),
        MouthFrameMetric(index=3, ratio=0.07, dark_share=0.44, audio_energy=0.05, shadow_share=0.50),
    ]

    summary = summarize_mouth_metrics(metrics, total_frames=4)

    assert summary["verdict"] == "needs_review"
    assert summary["low_energy_closed_leak_ratio"] == 0.5
    assert summary["low_energy_visible_gap_ratio"] == 0.5
    assert summary["jitter"]["p95_abs_delta"] > 0.18
    assert len(summary["warnings"]) >= 2


def test_mouth_naturalness_summary_does_not_fail_closed_lip_shape_without_visible_gap():
    metrics = [
        MouthFrameMetric(index=0, ratio=0.22, dark_share=0.0, audio_energy=0.02, shadow_share=0.0),
        MouthFrameMetric(index=1, ratio=0.24, dark_share=0.0, audio_energy=0.03, shadow_share=0.0),
        MouthFrameMetric(index=2, ratio=0.23, dark_share=0.0, audio_energy=0.04, shadow_share=0.0),
        MouthFrameMetric(index=3, ratio=0.26, dark_share=0.0, audio_energy=0.70, shadow_share=0.0),
    ]

    summary = summarize_mouth_metrics(metrics, total_frames=4)

    assert summary["low_energy_closed_leak_ratio"] == 1.0
    assert summary["low_energy_visible_gap_ratio"] == 0.0
    assert summary["verdict"] == "ok"


def test_mouth_naturalness_summary_flags_muted_high_energy_vowels():
    metrics = [
        MouthFrameMetric(index=0, ratio=0.10, dark_share=0.0, audio_energy=0.05, shadow_share=0.0),
        MouthFrameMetric(index=1, ratio=0.19, dark_share=0.0, audio_energy=0.70, shadow_share=0.0),
        MouthFrameMetric(index=2, ratio=0.21, dark_share=0.0, audio_energy=0.82, shadow_share=0.0),
        MouthFrameMetric(index=3, ratio=0.22, dark_share=0.0, audio_energy=0.76, shadow_share=0.0),
    ]

    summary = summarize_mouth_metrics(metrics, total_frames=4)

    assert summary["high_energy_muted_open_ratio"] == 1.0
    assert summary["verdict"] == "needs_review"
    assert any("muted" in warning for warning in summary["warnings"])


def test_mouth_naturalness_summary_accepts_clear_high_energy_opening():
    metrics = [
        MouthFrameMetric(index=0, ratio=0.10, dark_share=0.0, audio_energy=0.05, shadow_share=0.0),
        MouthFrameMetric(index=1, ratio=0.15, dark_share=0.0, audio_energy=0.20, shadow_share=0.0),
        MouthFrameMetric(index=2, ratio=0.22, dark_share=0.0, audio_energy=0.50, shadow_share=0.0),
        MouthFrameMetric(index=3, ratio=0.26, dark_share=0.0, audio_energy=0.70, shadow_share=0.0),
        MouthFrameMetric(index=4, ratio=0.29, dark_share=0.0, audio_energy=0.82, shadow_share=0.0),
        MouthFrameMetric(index=5, ratio=0.30, dark_share=0.0, audio_energy=0.90, shadow_share=0.0),
    ]

    summary = summarize_mouth_metrics(metrics, total_frames=6)

    assert summary["high_energy_muted_open_ratio"] == 0.0
    assert summary["verdict"] == "ok"


def test_mouth_naturalness_summary_handles_missing_landmarks():
    summary = summarize_mouth_metrics([], total_frames=30)

    assert summary["verdict"] == "insufficient_landmarks"
    assert summary["detection_rate"] == 0.0


def test_atlas_coverage_reports_good_closed_micro_and_open_range():
    metrics = [
        MouthFrameMetric(index=0, ratio=0.07, dark_share=0.05, audio_energy=0),
        MouthFrameMetric(index=1, ratio=0.09, dark_share=0.05, audio_energy=0),
        MouthFrameMetric(index=2, ratio=0.11, dark_share=0.05, audio_energy=0),
        MouthFrameMetric(index=3, ratio=0.16, dark_share=0.05, audio_energy=0),
        MouthFrameMetric(index=4, ratio=0.20, dark_share=0.05, audio_energy=0),
        MouthFrameMetric(index=5, ratio=0.34, dark_share=0.10, audio_energy=0),
    ]

    summary = summarize_atlas_coverage(metrics, total_frames=6)

    assert summary["verdict"] == "ok"
    assert summary["coverage"]["usable_closed_count"] == 3
    assert summary["coverage"]["micro_open_share"] > 0
    assert summary["coverage"]["open_share"] > 0


def test_atlas_coverage_flags_missing_closed_mouth_frames():
    metrics = [
        MouthFrameMetric(index=0, ratio=0.18, dark_share=0.05, audio_energy=0),
        MouthFrameMetric(index=1, ratio=0.22, dark_share=0.05, audio_energy=0),
        MouthFrameMetric(index=2, ratio=0.30, dark_share=0.05, audio_energy=0),
        MouthFrameMetric(index=3, ratio=0.34, dark_share=0.05, audio_energy=0),
    ]

    summary = summarize_atlas_coverage(metrics, total_frames=4)

    assert summary["verdict"] == "needs_better_reference"
    assert summary["coverage"]["usable_closed_count"] == 0
    assert any("closed-mouth" in warning for warning in summary["warnings"])


def test_mouth_state_alignment_reports_ok_phoneme_shape_match():
    metrics = [
        MouthFrameMetric(index=0, ratio=0.08, dark_share=0.0, audio_energy=0.0, shadow_share=0.0),
        MouthFrameMetric(index=1, ratio=0.12, dark_share=0.0, audio_energy=0.3, shadow_share=0.0),
        MouthFrameMetric(index=2, ratio=0.26, dark_share=0.0, audio_energy=0.7, shadow_share=0.0),
        MouthFrameMetric(index=3, ratio=0.30, dark_share=0.0, audio_energy=0.8, shadow_share=0.0),
    ]
    states = [
        {"index": 0, "state": "silence"},
        {"index": 1, "state": "consonant"},
        {"index": 2, "state": "vowel", "openness": 0.70},
        {"index": 3, "state": "vowel", "openness": 0.80},
    ]

    summary = summarize_mouth_state_alignment(metrics, states)

    assert summary["verdict"] == "ok"
    assert summary["closed_state_visible_gap_ratio"] == 0.0
    assert summary["consonant_over_open_ratio"] == 0.0
    assert summary["vowel_muted_ratio"] == 0.0
    assert summary["vowel_mean_ratio"] == 0.28
    assert summary["medium_vowel_frames"] == 2
    assert summary["medium_vowel_muted_ratio"] == 0.0


def test_mouth_state_alignment_flags_consonant_over_open_and_muted_vowel():
    metrics = [
        MouthFrameMetric(index=0, ratio=0.26, dark_share=0.0, audio_energy=0.3, shadow_share=0.0),
        MouthFrameMetric(index=1, ratio=0.28, dark_share=0.0, audio_energy=0.4, shadow_share=0.0),
        MouthFrameMetric(index=2, ratio=0.27, dark_share=0.0, audio_energy=0.5, shadow_share=0.0),
        MouthFrameMetric(index=3, ratio=0.18, dark_share=0.0, audio_energy=0.7, shadow_share=0.0),
        MouthFrameMetric(index=4, ratio=0.19, dark_share=0.0, audio_energy=0.8, shadow_share=0.0),
        MouthFrameMetric(index=5, ratio=0.20, dark_share=0.0, audio_energy=0.9, shadow_share=0.0),
    ]
    states = [
        {"index": 0, "state": "consonant"},
        {"index": 1, "state": "consonant"},
        {"index": 2, "state": "consonant"},
        {"index": 3, "state": "vowel", "openness": 0.75},
        {"index": 4, "state": "vowel", "openness": 0.82},
        {"index": 5, "state": "vowel", "openness": 0.90},
    ]

    summary = summarize_mouth_state_alignment(metrics, states)

    assert summary["verdict"] == "needs_review"
    assert summary["consonant_over_open_ratio"] == 1.0
    assert summary["vowel_muted_ratio"] == 1.0
    assert any("Consonant" in warning for warning in summary["warnings"])
    assert any("Vowel" in warning for warning in summary["warnings"])


def test_mouth_state_alignment_flags_muted_medium_vowels():
    metrics = [
        MouthFrameMetric(index=0, ratio=0.19, dark_share=0.0, audio_energy=0.30, shadow_share=0.0),
        MouthFrameMetric(index=1, ratio=0.20, dark_share=0.0, audio_energy=0.32, shadow_share=0.0),
        MouthFrameMetric(index=2, ratio=0.21, dark_share=0.0, audio_energy=0.34, shadow_share=0.0),
    ]
    states = [
        {"index": 0, "state": "vowel", "openness": 0.30, "energy": 0.30},
        {"index": 1, "state": "vowel", "openness": 0.32, "energy": 0.32},
        {"index": 2, "state": "vowel", "openness": 0.34, "energy": 0.34},
    ]

    summary = summarize_mouth_state_alignment(metrics, states)

    assert summary["verdict"] == "needs_review"
    assert summary["medium_vowel_frames"] == 3
    assert summary["medium_vowel_muted_ratio"] == 1.0
    assert any("Medium vowel" in warning for warning in summary["warnings"])


def test_mouth_state_alignment_flags_visible_gap_on_closed_states():
    metrics = [
        MouthFrameMetric(index=0, ratio=0.24, dark_share=0.0, audio_energy=0.0, shadow_share=0.20),
        MouthFrameMetric(index=1, ratio=0.25, dark_share=0.0, audio_energy=0.1, shadow_share=0.18),
        MouthFrameMetric(index=2, ratio=0.28, dark_share=0.0, audio_energy=0.7, shadow_share=0.0),
    ]
    states = [
        {"index": 0, "state": "silence"},
        {"index": 1, "state": "consonant_closed"},
        {"index": 2, "state": "vowel"},
    ]

    summary = summarize_mouth_state_alignment(metrics, states)

    assert summary["verdict"] == "needs_review"
    assert summary["closed_state_visible_gap_ratio"] == 1.0
    assert any("Closed" in warning for warning in summary["warnings"])
