import json
from pathlib import Path

from app.models import RenderOptions
from app.providers.digital_human import Wav2LipOnnxProvider
from app.settings import Settings


def assert_mouth_state_sidecar(blend_command, output):
    assert "--mouth-state-debug-output" in blend_command
    assert blend_command[blend_command.index("--mouth-state-debug-output") + 1] == str(
        output.with_suffix(".mouth_state.json")
    )


def assert_mouth_diagnosis_command(command, output, audio, *, sample_stride="2", max_frames="240"):
    assert "diagnose_mouth_naturalness.py" in command[1]
    assert command[command.index("--video") + 1] == str(output)
    assert command[command.index("--audio") + 1] == str(audio)
    assert command[command.index("--mouth-state") + 1] == str(output.with_suffix(".mouth_state.json"))
    assert command[command.index("--sample-stride") + 1] == sample_stride
    assert command[command.index("--max-frames") + 1] == max_frames
    assert command[command.index("--output") + 1] == str(output.with_suffix(".mouth_diagnosis.json"))


def test_wav2lip_provider_runs_mouth_only_blend(tmp_path, monkeypatch):
    model = tmp_path / "wav2lip.onnx"
    model.write_bytes(b"model")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"video")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "output.mp4"
    commands = []

    def fake_run(command, **kwargs):
        commands.append([str(item) for item in command])
        if "wav2lip_onnx.py" in str(command[1]):
            output_arg = command[command.index("--output") + 1]
            Path(output_arg).write_bytes(b"raw")
        if "blend_wav2lip_result.py" in str(command[1]):
            output_arg = command[command.index("--output") + 1]
            Path(output_arg).write_bytes(b"blended")
        if "diagnose_mouth_naturalness.py" in str(command[1]):
            output_arg = command[command.index("--output") + 1]
            Path(output_arg).write_text('{"verdict":"ok"}', encoding="utf-8")

    monkeypatch.setattr("app.providers.digital_human._run_command", fake_run)

    provider = Wav2LipOnnxProvider(
        model_path=str(model),
        python_executable="python",
        blend_enabled=True,
        blend_preset="balanced",
    )

    assert provider.render(
        reference_video=reference,
        driving_audio=audio,
        script="测试口播",
        options=None,
        output_path=output,
    ) == output

    assert len(commands) == 3
    assert "wav2lip_onnx.py" in commands[0][1]
    assert commands[0][-1].endswith("_wav2lip_raw.mp4")
    assert "blend_wav2lip_result.py" in commands[1][1]
    assert "--dynamic-preserve" in commands[1]
    assert "--open-closed-priority" in commands[1]
    assert commands[1][commands[1].index("--open-shape-trigger") + 1] == "0.250"
    assert commands[1][commands[1].index("--open-shape-openness") + 1] == "0.780"
    assert "--open-generated-priority" in commands[1]
    assert commands[1][commands[1].index("--source") + 1] == str(reference)
    assert commands[1][commands[1].index("--generated") + 1].endswith("_wav2lip_raw.mp4")
    assert_mouth_state_sidecar(commands[1], output)
    assert commands[1][commands[1].index("--aperture-atlas-source") + 1] == str(reference)
    assert commands[1][commands[1].index("--aperture-atlas-strength") + 1] == "0.500"
    assert commands[1][commands[1].index("--aperture-energy-threshold") + 1] == "0.240"
    assert commands[1][commands[1].index("--aperture-min-ratio") + 1] == "0.070"
    assert commands[1][commands[1].index("--aperture-max-ratio") + 1] == "0.360"
    assert_mouth_diagnosis_command(commands[2], output, audio)
    assert output.read_bytes() == b"blended"


def test_wav2lip_blend_preset_adds_seamless_edge(tmp_path, monkeypatch):
    model = tmp_path / "wav2lip.onnx"
    model.write_bytes(b"model")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"video")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "output.mp4"
    commands = []

    def fake_run(command, **kwargs):
        commands.append([str(item) for item in command])
        output_arg = command[command.index("--output") + 1]
        Path(output_arg).write_bytes(b"ok")

    monkeypatch.setattr("app.providers.digital_human._run_command", fake_run)

    provider = Wav2LipOnnxProvider(
        model_path=str(model),
        python_executable="python",
        blend_enabled=True,
        blend_preset="natural",
    )

    provider.render(
        reference_video=reference,
        driving_audio=audio,
        script="测试口播",
        options=None,
        output_path=output,
    )

    assert "--seamless-edge" in commands[1]


def test_wav2lip_provider_passes_aperture_atlas_options(tmp_path, monkeypatch):
    model = tmp_path / "wav2lip.onnx"
    model.write_bytes(b"model")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"video")
    atlas = tmp_path / "same-person.mp4"
    atlas.write_bytes(b"atlas")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "output.mp4"
    commands = []

    def fake_run(command, **kwargs):
        commands.append([str(item) for item in command])
        output_arg = command[command.index("--output") + 1]
        Path(output_arg).write_bytes(b"ok")

    monkeypatch.setattr("app.providers.digital_human._run_command", fake_run)

    provider = Wav2LipOnnxProvider(
        model_path=str(model),
        python_executable="python",
        blend_enabled=True,
        blend_preset="balanced",
        aperture_atlas_source=str(atlas),
        aperture_atlas_strength=0.55,
        aperture_energy_threshold=0.24,
        aperture_min_ratio=0.07,
        aperture_max_ratio=0.36,
        aperture_attack=0.5,
        aperture_release=0.2,
    )

    provider.render(
        reference_video=reference,
        driving_audio=audio,
        script="测试口播",
        options=None,
        output_path=output,
    )

    blend_command = commands[1]
    assert_mouth_state_sidecar(blend_command, output)
    assert "--aperture-atlas-source" in blend_command
    assert blend_command[blend_command.index("--aperture-atlas-source") + 1] == str(atlas)
    assert "--aperture-atlas-strength" in blend_command
    assert blend_command[blend_command.index("--aperture-atlas-strength") + 1] == "0.550"
    assert blend_command[blend_command.index("--aperture-energy-threshold") + 1] == "0.240"
    assert blend_command[blend_command.index("--aperture-min-ratio") + 1] == "0.070"
    assert blend_command[blend_command.index("--aperture-max-ratio") + 1] == "0.360"
    assert blend_command[blend_command.index("--aperture-attack") + 1] == "0.500"
    assert blend_command[blend_command.index("--aperture-release") + 1] == "0.200"


def test_wav2lip_provider_passes_quality_diagnostics_limits(tmp_path, monkeypatch):
    model = tmp_path / "wav2lip.onnx"
    model.write_bytes(b"model")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"video")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "output.mp4"
    commands = []

    def fake_run(command, **kwargs):
        commands.append([str(item) for item in command])
        output_arg = command[command.index("--output") + 1]
        Path(output_arg).write_bytes(b"ok")

    monkeypatch.setattr("app.providers.digital_human._run_command", fake_run)

    provider = Wav2LipOnnxProvider(
        model_path=str(model),
        python_executable="python",
        blend_enabled=True,
        quality_diagnostics_sample_stride=3,
        quality_diagnostics_max_frames=80,
    )

    provider.render(
        reference_video=reference,
        driving_audio=audio,
        script="测试口播",
        options=None,
        output_path=output,
    )

    assert_mouth_diagnosis_command(commands[2], output, audio, sample_stride="3", max_frames="80")


def test_wav2lip_provider_uses_reference_as_aperture_atlas_when_source_unset(tmp_path, monkeypatch):
    model = tmp_path / "wav2lip.onnx"
    model.write_bytes(b"model")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"video")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "output.mp4"
    commands = []

    def fake_run(command, **kwargs):
        commands.append([str(item) for item in command])
        output_arg = command[command.index("--output") + 1]
        Path(output_arg).write_bytes(b"ok")

    monkeypatch.setattr("app.providers.digital_human._run_command", fake_run)

    provider = Wav2LipOnnxProvider(
        model_path=str(model),
        python_executable="python",
        blend_enabled=True,
        blend_preset="balanced",
        aperture_atlas_strength=0.5,
    )

    provider.render(
        reference_video=reference,
        driving_audio=audio,
        script="测试口播",
        options=None,
        output_path=output,
    )

    blend_command = commands[1]
    assert_mouth_state_sidecar(blend_command, output)
    assert blend_command[blend_command.index("--aperture-atlas-source") + 1] == str(reference)
    assert blend_command[blend_command.index("--aperture-atlas-strength") + 1] == "0.500"


def test_wav2lip_provider_defaults_enable_automatic_reference_aperture_atlas(tmp_path, monkeypatch):
    model = tmp_path / "wav2lip.onnx"
    model.write_bytes(b"model")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"video")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "output.mp4"
    commands = []

    def fake_run(command, **kwargs):
        commands.append([str(item) for item in command])
        output_arg = command[command.index("--output") + 1]
        Path(output_arg).write_bytes(b"ok")

    monkeypatch.setattr("app.providers.digital_human._run_command", fake_run)
    settings = Settings(wav2lip_onnx_model=str(model), wav2lip_aperture_atlas_source=None)

    provider = Wav2LipOnnxProvider(
        model_path=settings.wav2lip_onnx_model,
        python_executable="python",
        blend_enabled=settings.wav2lip_blend_enabled,
        blend_preset=settings.wav2lip_blend_preset,
        aperture_atlas_source=settings.wav2lip_aperture_atlas_source,
        aperture_atlas_strength=settings.wav2lip_aperture_atlas_strength,
        aperture_energy_threshold=settings.wav2lip_aperture_energy_threshold,
        aperture_min_ratio=settings.wav2lip_aperture_min_ratio,
        aperture_max_ratio=settings.wav2lip_aperture_max_ratio,
        aperture_attack=settings.wav2lip_aperture_attack,
        aperture_release=settings.wav2lip_aperture_release,
    )

    provider.render(
        reference_video=reference,
        driving_audio=audio,
        script="测试口播",
        options=None,
        output_path=output,
    )

    blend_command = commands[1]
    assert_mouth_state_sidecar(blend_command, output)
    assert blend_command[blend_command.index("--aperture-atlas-source") + 1] == str(reference)
    assert blend_command[blend_command.index("--aperture-atlas-strength") + 1] == "0.500"
    assert blend_command[blend_command.index("--aperture-energy-threshold") + 1] == "0.240"
    assert blend_command[blend_command.index("--aperture-min-ratio") + 1] == "0.070"
    assert blend_command[blend_command.index("--aperture-max-ratio") + 1] == "0.360"


def test_wav2lip_provider_allows_render_options_to_enable_aperture_atlas(tmp_path, monkeypatch):
    model = tmp_path / "wav2lip.onnx"
    model.write_bytes(b"model")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"video")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "output.mp4"
    commands = []

    def fake_run(command, **kwargs):
        commands.append([str(item) for item in command])
        output_arg = command[command.index("--output") + 1]
        Path(output_arg).write_bytes(b"ok")

    monkeypatch.setattr("app.providers.digital_human._run_command", fake_run)

    provider = Wav2LipOnnxProvider(
        model_path=str(model),
        python_executable="python",
        blend_enabled=True,
        blend_preset="balanced",
        aperture_atlas_strength=0.0,
    )

    provider.render(
        reference_video=reference,
        driving_audio=audio,
        script="测试口播",
        options=RenderOptions(
            mouth_aperture_enabled=True,
            mouth_aperture_strength=0.48,
            mouth_aperture_energy_threshold=0.26,
            mouth_aperture_min_ratio=0.06,
            mouth_aperture_max_ratio=0.35,
            mouth_aperture_attack=1.0,
            mouth_aperture_release=0.9,
        ),
        output_path=output,
    )

    blend_command = commands[1]
    assert blend_command[blend_command.index("--aperture-atlas-source") + 1] == str(reference)
    assert blend_command[blend_command.index("--aperture-atlas-strength") + 1] == "0.480"
    assert blend_command[blend_command.index("--aperture-energy-threshold") + 1] == "0.260"
    assert blend_command[blend_command.index("--aperture-min-ratio") + 1] == "0.060"
    assert blend_command[blend_command.index("--aperture-max-ratio") + 1] == "0.350"
    assert blend_command[blend_command.index("--aperture-attack") + 1] == "1.000"
    assert blend_command[blend_command.index("--aperture-release") + 1] == "0.900"


def test_wav2lip_provider_render_options_can_disable_env_aperture_atlas(tmp_path, monkeypatch):
    model = tmp_path / "wav2lip.onnx"
    model.write_bytes(b"model")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"video")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "output.mp4"
    commands = []

    def fake_run(command, **kwargs):
        commands.append([str(item) for item in command])
        output_arg = command[command.index("--output") + 1]
        Path(output_arg).write_bytes(b"ok")

    monkeypatch.setattr("app.providers.digital_human._run_command", fake_run)

    provider = Wav2LipOnnxProvider(
        model_path=str(model),
        python_executable="python",
        blend_enabled=True,
        blend_preset="balanced",
        aperture_atlas_strength=0.5,
    )

    provider.render(
        reference_video=reference,
        driving_audio=audio,
        script="测试口播",
        options=RenderOptions(mouth_aperture_enabled=False),
        output_path=output,
    )

    assert_mouth_state_sidecar(commands[1], output)
    assert "--aperture-atlas-source" not in commands[1]


def test_wav2lip_provider_can_disable_internal_quality_diagnostics(tmp_path, monkeypatch):
    model = tmp_path / "wav2lip.onnx"
    model.write_bytes(b"model")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"video")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "output.mp4"
    commands = []

    def fake_run(command, **kwargs):
        commands.append([str(item) for item in command])
        output_arg = command[command.index("--output") + 1]
        Path(output_arg).write_bytes(b"ok")

    monkeypatch.setattr("app.providers.digital_human._run_command", fake_run)

    provider = Wav2LipOnnxProvider(
        model_path=str(model),
        python_executable="python",
        blend_enabled=True,
        quality_diagnostics_enabled=False,
    )

    provider.render(
        reference_video=reference,
        driving_audio=audio,
        script="测试口播",
        options=None,
        output_path=output,
    )

    assert len(commands) == 2
    assert "diagnose_mouth_naturalness.py" not in " ".join(" ".join(command) for command in commands)


def test_wav2lip_provider_quality_diagnostics_failure_does_not_block_render(tmp_path, monkeypatch):
    model = tmp_path / "wav2lip.onnx"
    model.write_bytes(b"model")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"video")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "output.mp4"
    commands = []

    def fake_run(command, **kwargs):
        commands.append([str(item) for item in command])
        if "diagnose_mouth_naturalness.py" in str(command[1]):
            raise RuntimeError("diagnostic boom")
        output_arg = command[command.index("--output") + 1]
        Path(output_arg).write_bytes(b"ok")

    monkeypatch.setattr("app.providers.digital_human._run_command", fake_run)

    provider = Wav2LipOnnxProvider(
        model_path=str(model),
        python_executable="python",
        blend_enabled=True,
    )

    assert provider.render(
        reference_video=reference,
        driving_audio=audio,
        script="测试口播",
        options=None,
        output_path=output,
    ) == output

    assert output.exists()
    assert_mouth_diagnosis_command(commands[2], output, audio)
    diagnosis = json.loads(output.with_suffix(".mouth_diagnosis.json").read_text(encoding="utf-8"))
    assert diagnosis["verdict"] == "diagnostics_unavailable"
    assert "diagnostic boom" in diagnosis["error"]
