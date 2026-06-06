import pytest

from tools.blend_wav2lip_result import (
    MouthStateFrame,
    MouthTexture,
    aperture_control_from_mouth_state,
    aperture_ratio_from_energy,
    apply_vowel_release_floor,
    audio_mouth_state_controller,
    choose_aperture_target,
    generated_open_priority_blend,
    mouth_state_openness_levels,
    mouth_open_ratio,
    open_geometry_target_points,
    open_closed_priority_shape,
    summarize_mouth_states,
    target_open_geometry_ratio,
    warp_open_mouth_geometry,
)


def _mouth_points(ratio: float):
    import numpy as np

    points = np.zeros((20, 2), dtype=np.float32)
    points[:12, 0] = np.linspace(40, 80, 12)
    points[:12, 1] = np.linspace(50, 58, 12)
    width = 40.0
    height = width * ratio
    points[12:20, 0] = np.linspace(40, 80, 8)
    points[12:20, 1] = np.array([60, 60, 60, 60 + height, 60 + height, 60 + height, 60, 60], dtype=np.float32)
    return points


def _texture(ratio: float):
    import numpy as np

    return MouthTexture(
        frame=np.zeros((100, 100, 3), dtype=np.uint8),
        mouth_points=_mouth_points(ratio),
        ratio=ratio,
        score=0.0,
        index=0,
    )


def test_aperture_ratio_keeps_low_energy_closed():
    ratio = aperture_ratio_from_energy(
        0.18,
        energy_threshold=0.24,
        min_ratio=0.07,
        max_ratio=0.36,
    )

    assert ratio == pytest.approx(0.07)


def test_aperture_ratio_eases_toward_micro_open_state():
    ratio = aperture_ratio_from_energy(
        0.62,
        energy_threshold=0.24,
        min_ratio=0.07,
        max_ratio=0.36,
    )

    assert 0.20 < ratio < 0.24


def test_aperture_ratio_clamps_to_person_specific_range():
    ratio = aperture_ratio_from_energy(
        1.0,
        energy_threshold=0.24,
        min_ratio=0.07,
        max_ratio=0.36,
    )

    assert ratio == pytest.approx(0.36)


def test_closed_lock_keeps_aperture_target_from_following_generated_open_mouth():
    atlas = [_texture(0.06), _texture(0.12), _texture(0.36)]
    generated_open_mouth = _mouth_points(0.36)

    unlocked = choose_aperture_target(atlas, generated_open_mouth, 0.06, closed_lock=False)
    locked = choose_aperture_target(atlas, generated_open_mouth, 0.06, closed_lock=True)

    assert unlocked is not None
    assert locked is not None
    assert unlocked.ratio > locked.ratio
    assert locked.ratio == pytest.approx(0.06)


def test_mouth_state_controller_holds_silence_closed():
    import numpy as np

    levels = np.array([0.0, 0.04, 0.18, 0.23, 0.22], dtype=np.float32)

    controlled = mouth_state_openness_levels(levels, close_threshold=0.24)

    assert np.max(controlled) == pytest.approx(0.0)


def test_mouth_state_controller_releases_into_open_state():
    import numpy as np

    levels = np.array([0.0, 0.12, 0.26, 0.42, 0.68, 0.76], dtype=np.float32)

    controlled = mouth_state_openness_levels(levels, close_threshold=0.24, attack=0.8, release=0.8)

    assert controlled[2] < 0.02
    assert controlled[-1] > 0.60


def test_audio_mouth_state_controller_holds_silence_closed():
    import numpy as np

    samples = np.zeros(16000, dtype=np.float32)

    states = audio_mouth_state_controller(
        samples,
        16000,
        25,
        25,
        close_threshold=0.24,
    )

    assert {state.state for state in states} == {"silence"}
    assert max(state.openness for state in states) == pytest.approx(0.0)


def test_audio_mouth_state_controller_releases_voiced_vowel_after_silence():
    import numpy as np

    sample_rate = 16000
    silence = np.zeros(int(sample_rate * 0.24), dtype=np.float32)
    t = np.arange(int(sample_rate * 0.76), dtype=np.float32) / sample_rate
    vowel = (np.sin(2.0 * np.pi * 220.0 * t) * 0.55).astype(np.float32)
    samples = np.concatenate([silence, vowel])

    states = audio_mouth_state_controller(
        samples,
        sample_rate,
        25,
        25,
        close_threshold=0.24,
    )

    assert all(state.openness == pytest.approx(0.0) for state in states[:5])
    assert any(state.state == "vowel" for state in states[8:])
    assert max(state.openness for state in states[10:]) > 0.55


def test_audio_mouth_state_controller_keeps_noisy_consonant_micro_open():
    import numpy as np

    sample_rate = 16000
    rng = np.random.default_rng(7)
    silence = np.zeros(int(sample_rate * 0.24), dtype=np.float32)
    hiss = (rng.normal(0.0, 0.12, int(sample_rate * 0.76))).astype(np.float32)
    samples = np.concatenate([silence, hiss])

    states = audio_mouth_state_controller(
        samples,
        sample_rate,
        25,
        25,
        close_threshold=0.24,
    )

    assert any(state.state == "consonant" for state in states[8:])
    assert max(state.openness for state in states[8:]) < 0.32


def test_summarize_mouth_states_reports_internal_state_mix():
    states = [
        MouthStateFrame(energy=0.0, centroid=0.0, zero_crossing=0.0, high_band_share=0.0, state="silence", openness=0.0),
        MouthStateFrame(energy=0.3, centroid=0.7, zero_crossing=0.4, high_band_share=0.5, state="consonant", openness=0.2),
        MouthStateFrame(energy=0.8, centroid=0.1, zero_crossing=0.03, high_band_share=0.0, state="vowel", openness=0.7),
    ]

    summary = summarize_mouth_states(states)

    assert summary["total_frames"] == 3
    assert summary["state_counts"] == {"silence": 1, "consonant": 1, "vowel": 1}
    assert summary["state_shares"]["vowel"] == pytest.approx(0.3333)
    assert summary["openness"]["max"] == 0.7
    assert summary["frames"][1]["state"] == "consonant"


def test_aperture_control_keeps_consonant_from_following_raw_energy_opening():
    state = MouthStateFrame(
        energy=0.82,
        centroid=0.8,
        zero_crossing=0.45,
        high_band_share=0.62,
        state="consonant",
        openness=0.21,
    )

    aperture_driver, target_lock, closed_lock = aperture_control_from_mouth_state(
        0.88,
        state,
        energy_threshold=0.24,
    )

    assert aperture_driver < 0.26
    assert target_lock is True
    assert closed_lock is False


def test_aperture_control_does_not_target_lock_ambiguous_consonant():
    state = MouthStateFrame(
        energy=0.33,
        centroid=0.41,
        zero_crossing=0.20,
        high_band_share=0.07,
        state="consonant",
        openness=0.16,
    )

    aperture_driver, target_lock, closed_lock = aperture_control_from_mouth_state(
        0.33,
        state,
        energy_threshold=0.24,
    )

    assert aperture_driver < 0.25
    assert target_lock is False
    assert closed_lock is False


def test_aperture_control_allows_vowel_release_to_follow_raw_energy():
    state = MouthStateFrame(
        energy=0.65,
        centroid=0.1,
        zero_crossing=0.03,
        high_band_share=0.02,
        state="vowel",
        openness=0.42,
    )

    aperture_driver, target_lock, closed_lock = aperture_control_from_mouth_state(
        0.74,
        state,
        energy_threshold=0.24,
    )

    assert aperture_driver == pytest.approx(0.74)
    assert target_lock is False
    assert closed_lock is False


def test_aperture_control_keeps_low_energy_vowel_frame_closed():
    state = MouthStateFrame(
        energy=0.22,
        centroid=0.1,
        zero_crossing=0.03,
        high_band_share=0.02,
        state="vowel",
        openness=0.38,
    )

    aperture_driver, target_lock, closed_lock = aperture_control_from_mouth_state(
        0.18,
        state,
        energy_threshold=0.24,
    )

    assert aperture_driver == pytest.approx(0.0)
    assert target_lock is True
    assert closed_lock is True


def test_aperture_control_locks_silence_closed():
    state = MouthStateFrame(
        energy=0.0,
        centroid=0.0,
        zero_crossing=0.0,
        high_band_share=0.0,
        state="silence",
        openness=0.0,
    )

    aperture_driver, target_lock, closed_lock = aperture_control_from_mouth_state(
        0.34,
        state,
        energy_threshold=0.24,
    )

    assert aperture_driver == pytest.approx(0.0)
    assert target_lock is True
    assert closed_lock is True


def test_vowel_release_floor_lifts_expected_open_vowel_target():
    state = MouthStateFrame(
        energy=0.50,
        centroid=0.1,
        zero_crossing=0.03,
        high_band_share=0.01,
        state="vowel",
        openness=0.50,
    )

    target = apply_vowel_release_floor(
        0.12,
        state,
        min_ratio=0.07,
        max_ratio=0.36,
        target_lock=False,
        closed_lock=False,
    )

    assert target == pytest.approx(0.244)


def test_vowel_release_floor_does_not_lift_locked_or_weak_frames():
    weak_vowel = MouthStateFrame(
        energy=0.30,
        centroid=0.1,
        zero_crossing=0.03,
        high_band_share=0.01,
        state="vowel",
        openness=0.30,
    )
    consonant = MouthStateFrame(
        energy=0.70,
        centroid=0.9,
        zero_crossing=0.5,
        high_band_share=0.6,
        state="consonant",
        openness=0.20,
    )

    assert apply_vowel_release_floor(
        0.12,
        weak_vowel,
        min_ratio=0.07,
        max_ratio=0.36,
        target_lock=False,
        closed_lock=False,
    ) == pytest.approx(0.12)
    assert apply_vowel_release_floor(
        0.12,
        weak_vowel,
        min_ratio=0.07,
        max_ratio=0.36,
        target_lock=True,
        closed_lock=True,
    ) == pytest.approx(0.12)
    assert apply_vowel_release_floor(
        0.12,
        consonant,
        min_ratio=0.07,
        max_ratio=0.36,
        target_lock=False,
        closed_lock=False,
    ) == pytest.approx(0.12)


def test_open_closed_priority_forces_expected_open_vowel_shape():
    state = MouthStateFrame(
        energy=0.55,
        centroid=0.1,
        zero_crossing=0.03,
        high_band_share=0.01,
        state="vowel",
        openness=0.50,
    )

    openness, force_open = open_closed_priority_shape(
        0.28,
        state,
        enabled=True,
        trigger=0.42,
        open_openness=0.76,
        target_lock=False,
        closed_lock=False,
    )

    assert openness == pytest.approx(0.76)
    assert force_open is True


def test_open_closed_priority_releases_strong_vowel_shape_more():
    state = MouthStateFrame(
        energy=0.88,
        centroid=0.1,
        zero_crossing=0.03,
        high_band_share=0.01,
        state="vowel",
        openness=0.84,
    )

    openness, force_open = open_closed_priority_shape(
        0.44,
        state,
        enabled=True,
        trigger=0.42,
        open_openness=0.78,
        target_lock=False,
        closed_lock=False,
    )

    assert openness > 0.79
    assert openness <= 0.92
    assert force_open is True


def test_open_closed_priority_does_not_override_closed_or_non_vowel_frames():
    closed_vowel = MouthStateFrame(
        energy=0.52,
        centroid=0.1,
        zero_crossing=0.03,
        high_band_share=0.01,
        state="vowel",
        openness=0.52,
    )
    consonant = MouthStateFrame(
        energy=0.70,
        centroid=0.9,
        zero_crossing=0.5,
        high_band_share=0.6,
        state="consonant",
        openness=0.20,
    )

    locked_openness, locked_force_open = open_closed_priority_shape(
        0.22,
        closed_vowel,
        enabled=True,
        trigger=0.42,
        open_openness=0.76,
        target_lock=True,
        closed_lock=True,
    )
    consonant_openness, consonant_force_open = open_closed_priority_shape(
        0.22,
        consonant,
        enabled=True,
        trigger=0.42,
        open_openness=0.76,
        target_lock=False,
        closed_lock=False,
    )

    assert locked_openness == pytest.approx(0.22)
    assert locked_force_open is False
    assert consonant_openness == pytest.approx(0.22)
    assert consonant_force_open is False


def test_target_open_geometry_ratio_lifts_weak_open_shape():
    weak_open = _mouth_points(0.16)

    target = target_open_geometry_ratio(weak_open, 0.80, max_ratio=0.38)

    assert target > 0.34
    assert target <= 0.38


def test_open_geometry_target_points_expand_inner_aperture():
    weak_open = _mouth_points(0.16)

    target_points = open_geometry_target_points(weak_open, 0.80, max_ratio=0.38)

    assert mouth_open_ratio(target_points) > mouth_open_ratio(weak_open)


def test_open_geometry_warp_only_changes_strong_open_frames():
    import numpy as np

    pytest.importorskip("cv2")

    points = _mouth_points(0.16)
    image = np.zeros((120, 120, 3), dtype=np.uint8)
    image[52:68, 44:78] = 180

    weak = warp_open_mouth_geometry(image, points, 0.30, enabled=True)
    open_warped = warp_open_mouth_geometry(image, points, 0.80, enabled=True)
    disabled = warp_open_mouth_geometry(image, points, 0.80, enabled=False)

    assert np.array_equal(weak, image)
    assert np.array_equal(disabled, image)
    assert not np.array_equal(open_warped, image)


def test_generated_open_priority_blend_preserves_generated_mouth_pixels():
    import numpy as np

    pytest.importorskip("cv2")

    points = _mouth_points(0.28)
    source = np.full((120, 120, 3), 180, dtype=np.uint8)
    generated = source.copy()
    generated[54:72, 45:78] = [72, 42, 40]

    blended, mask, inner_mask = generated_open_priority_blend(source, generated, points, 0.86)

    assert mask.max() > 0.90
    assert inner_mask.max() > 0.40
    assert blended[62, 60].mean() < source[62, 60].mean()
