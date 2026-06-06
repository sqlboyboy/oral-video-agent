from pathlib import Path

from app.models import RenderOptions
from app.pipeline.renderer import Renderer


def test_build_ffmpeg_command_maps_video_voice_bgm_and_subtitles(tmp_path):
    renderer = Renderer()
    source = tmp_path / "source.mp4"
    voice = tmp_path / "voice.wav"
    subtitle = tmp_path / "subtitle.srt"
    bgm = tmp_path / "bgm.mp3"
    output = tmp_path / "output.mp4"

    command = renderer.build_ffmpeg_command(
        source,
        voice,
        subtitle,
        RenderOptions(voice_id="default-female", bgm_id="custom:bgm", bgm_volume=0.25),
        output,
        bgm,
    )

    assert Path(command[0]).name.startswith("ffmpeg")
    assert command[1:4] == ["-y", "-i", str(source)]
    assert str(voice) in command
    assert str(bgm) in command
    assert "-filter_complex" in command
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "volume=0.25" in filter_complex
    assert "amix=inputs=2" in filter_complex
    assert "subtitles=" in filter_complex
    assert command[-1] == str(output)


def test_renderer_writes_placeholder_when_real_inputs_are_missing(tmp_path):
    renderer = Renderer()
    output = tmp_path / "placeholder.mp4.txt"

    result = renderer.render(
        "task-1",
        "测试口播文案",
        RenderOptions(voice_id="default-female", bgm_id="default-light"),
        output,
    )

    assert result == output
    text = output.read_text(encoding="utf-8")
    assert "Real FFmpeg rendering is skipped" in text
    assert "task_id=task-1" in text
    assert "测试口播文案" in text
