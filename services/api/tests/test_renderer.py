from pathlib import Path

import app.pipeline.renderer as renderer_module
from app.models import RenderOptions
from app.pipeline.renderer import Renderer


def test_build_cover_first_frame_command_replaces_only_frame_zero(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    cover = tmp_path / "cover.png"
    output = tmp_path / "covered.mp4"
    monkeypatch.setattr(renderer_module, "_ffmpeg_executable", lambda: "ffmpeg")
    monkeypatch.setattr(renderer_module, "_canvas_dimensions", lambda _: (720, 1280))

    command = Renderer().build_cover_first_frame_command(source, cover, output)

    assert command[:4] == ["ffmpeg", "-y", "-i", str(source)]
    assert str(cover) in command
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "scale=720:1280" in filter_complex
    assert "overlay=0:0:enable='eq(n\\,0)'" in filter_complex
    assert command[command.index("-map") + 1] == "[vout]"
    assert "0:a?" in command
    assert command[command.index("-c:a") + 1] == "copy"
    assert command[-1] == str(output)


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
        RenderOptions(
            voice_id="default-female",
            voice_volume=0.45,
            bgm_id="custom:bgm",
            bgm_volume=0.25,
        ),
        output,
        bgm,
    )

    assert Path(command[0]).name.startswith("ffmpeg")
    assert command[1:4] == ["-y", "-i", str(source)]
    assert str(voice) in command
    assert str(bgm) in command
    assert "-filter_complex" in command
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "[1:a]volume=0.45[voice]" in filter_complex
    assert "[2:a]volume=0.25,aloop=loop=-1:size=2147483647[bgm]" in filter_complex
    assert "loudnorm" not in filter_complex
    assert "amix=inputs=2" in filter_complex
    assert "normalize=0" in filter_complex
    assert "subtitles=" in filter_complex
    assert "FontSize=9.6" in filter_complex
    assert "Outline=0.75" in filter_complex
    assert "MarginV=77" in filter_complex
    assert command[command.index("-preset") + 1] == "veryfast"
    assert command[command.index("-crf") + 1] == "18"
    assert "-r" not in command
    assert command[-1] == str(output)


def test_custom_subtitle_position_maps_drag_coordinates_to_libass(tmp_path):
    renderer = Renderer()
    source = tmp_path / "source.mp4"
    voice = tmp_path / "voice.wav"
    subtitle = tmp_path / "subtitle.srt"
    output = tmp_path / "output.mp4"

    command = renderer.build_ffmpeg_command(
        source,
        voice,
        subtitle,
        RenderOptions(
            subtitle_style={
                "position": "custom",
                "position_x": 0.7,
                "position_y": 0.31,
            }
        ),
        output,
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "Alignment=8" in filter_complex
    assert "MarginV=89" in filter_complex
    assert "MarginL=160" in filter_complex
    assert "MarginR=7" in filter_complex


def test_ass_subtitles_keep_native_portrait_coordinates(tmp_path):
    renderer = Renderer()
    source = tmp_path / "source.mp4"
    voice = tmp_path / "voice.wav"
    subtitle = tmp_path / "subtitle.ass"
    output = tmp_path / "output.mp4"

    command = renderer.build_ffmpeg_command(
        source,
        voice,
        subtitle,
        RenderOptions(),
        output,
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "subtitles=" in filter_complex
    assert "force_style=" not in filter_complex


def test_build_ffmpeg_command_overlays_pip_with_timing(tmp_path):
    renderer = Renderer()
    source = tmp_path / "source.mp4"
    voice = tmp_path / "voice.wav"
    subtitle = tmp_path / "subtitle.srt"
    pip = tmp_path / "pip.png"
    output = tmp_path / "output.mp4"

    command = renderer.build_ffmpeg_command(
        source,
        voice,
        subtitle,
        RenderOptions(
            voice_id="default-female",
            pip_enabled=True,
            pip_asset_id="pip-1",
            pip_position="bottom_left",
            pip_scale=0.25,
            pip_timing_mode="time",
            pip_start_seconds=2,
            pip_end_seconds=5,
        ),
        output,
        pip_asset=pip,
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "-loop" in command
    assert str(pip) in command
    assert "[0:v]scale=1080:1920:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[mainv]" in filter_complex
    assert "[2:v]scale=270:152:force_original_aspect_ratio=increase,crop=270:152,setsar=1,setpts=PTS-STARTPTS[pip]" in filter_complex
    assert "[mainv][pip]overlay=24:1744:enable='between(t\\,2.000\\,5.000)':eof_action=pass" in filter_complex


def test_build_ffmpeg_command_overlays_custom_pip_rect(tmp_path):
    renderer = Renderer()
    source = tmp_path / "source.mp4"
    voice = tmp_path / "voice.wav"
    pip = tmp_path / "pip.mp4"
    output = tmp_path / "output.mp4"

    command = renderer.build_ffmpeg_command(
        source,
        voice,
        None,
        RenderOptions(
            voice_id="default-female",
            pip_enabled=True,
            pip_asset_id="pip-1",
            pip_position="custom",
            pip_x=0.10,
            pip_y=0.20,
            pip_width=0.50,
            pip_height=0.20,
        ),
        output,
        pip_asset=pip,
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "-stream_loop" in command
    assert "[2:v]scale=540:384:force_original_aspect_ratio=increase,crop=540:384,setsar=1,setpts=PTS-STARTPTS[pip]" in filter_complex
    assert "[mainv][pip]overlay=108:384:eof_action=pass" in filter_complex


def test_build_ffmpeg_command_overlays_fullscreen_pip(tmp_path):
    renderer = Renderer()
    source = tmp_path / "source.mp4"
    voice = tmp_path / "voice.wav"
    pip = tmp_path / "pip.png"
    output = tmp_path / "output.mp4"

    command = renderer.build_ffmpeg_command(
        source,
        voice,
        None,
        RenderOptions(
            voice_id="default-female",
            pip_enabled=True,
            pip_asset_id="pip-1",
            pip_position="fullscreen",
        ),
        output,
        pip_asset=pip,
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "[2:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,setpts=PTS-STARTPTS[pip]" in filter_complex
    assert "[mainv][pip]overlay=0:0:eof_action=pass" in filter_complex


def test_build_postprocess_command_preserves_source_audio_and_fullscreen_pip(tmp_path, monkeypatch):
    renderer = Renderer()
    source = tmp_path / "cloud.mp4"
    subtitle = tmp_path / "subtitle.srt"
    pip = tmp_path / "pip.png"
    output = tmp_path / "output.mp4"
    monkeypatch.setattr(renderer_module, "media_video_dimensions", lambda _: (720, 1280))
    monkeypatch.setattr(renderer_module, "media_video_frame_rate", lambda _: "30")

    command = renderer.build_postprocess_command(
        source,
        subtitle,
        RenderOptions(
            voice_id="default-female",
            subtitle_enabled=True,
            pip_enabled=True,
            pip_asset_id="pip-1",
            pip_position="fullscreen",
        ),
        output,
        pip_asset=pip,
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert command[1:4] == ["-y", "-i", str(source)]
    assert "[0:a]volume=0.45[aout]" in filter_complex
    assert "[0:v]scale=720:1280:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[mainv]" in filter_complex
    assert "[1:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,setpts=PTS-STARTPTS[pip]" in filter_complex
    assert "[mainv][pip]overlay=0:0:eof_action=pass" in filter_complex
    assert "subtitles=" in filter_complex
    assert command[command.index("-r") + 1] == "30"


def test_postprocess_applies_each_linear_volume_once_to_normalized_audio(tmp_path):
    source = tmp_path / "digital-human.mp4"
    voice = tmp_path / "voice-lufs16.wav"
    bgm = tmp_path / "bgm.wav"
    output = tmp_path / "final.mp4"

    command = Renderer().build_postprocess_command(
        source,
        None,
        RenderOptions(
            subtitle_enabled=False,
            voice_volume=0.62,
            bgm_id="custom:bgm",
            bgm_volume=0.18,
        ),
        output,
        bgm_audio=bgm,
        voice_audio=voice,
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert command[4:7] == ["-i", str(voice), "-i"]
    assert "[1:a]volume=0.62[voice]" in filter_complex
    assert (
        "[2:a]volume=0.18,"
        "aloop=loop=-1:size=2147483647[bgm]"
    ) in filter_complex
    assert "loudnorm" not in filter_complex
    assert "amix=inputs=2:duration=first:dropout_transition=2:normalize=0" in filter_complex


def test_build_postprocess_command_copies_video_when_no_visual_filter(tmp_path):
    source = tmp_path / "cloud.mp4"
    output = tmp_path / "output.mp4"

    command = Renderer().build_postprocess_command(
        source,
        None,
        RenderOptions(subtitle_enabled=False, pip_enabled=False),
        output,
    )

    assert command[command.index("-map") + 1] == "0:v:0"
    assert command[command.index("-c:v") + 1] == "copy"
    assert "libx264" not in command
    assert "scale=" not in command[command.index("-filter_complex") + 1]


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
