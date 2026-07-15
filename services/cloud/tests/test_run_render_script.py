from __future__ import annotations

import json
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import worker.run_render as run_render_module
from worker.run_render import (
    build_render_payload,
    bounded_rewrite_chars,
    compose_final_video,
    find_bgm_audio_asset,
    find_cover_asset,
    find_pip_asset,
    find_source_asset,
    find_voice_audio_asset,
    find_voice_reference_asset,
    generate_srt_file,
    pip_enable_expression,
    prepare_cosyvoice_reference_audio,
    run_job,
    run_preprocess_job,
    should_compose_final,
    subtitle_force_style,
    to_simplified_chinese,
    wrap_text,
)


class LocalRenderApiHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length)
        if self.path == "/api/tasks/upload":
            assert b"source-video-bytes" in body
            assert "multipart/form-data" in self.headers.get("Content-Type", "")
            self._json({"task_id": "task-123"})
            return
        if self.path == "/api/tasks/task-123/render":
            self.server.render_payload = json.loads(body.decode("utf-8"))  # type: ignore[attr-defined]
            self._json(
                {
                    "task_id": "task-123",
                    "status": "completed",
                    "output_video_path": str(self.server.output_source),  # type: ignore[attr-defined]
                }
            )
            return
        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _json(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _start_server(output_source: Path) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalRenderApiHandler)
    server.output_source = output_source  # type: ignore[attr-defined]
    server.render_payload = None  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_run_job_uses_local_render_api_and_writes_worker_output(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source-video-bytes")
    rendered = tmp_path / "rendered.mp4"
    rendered.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 2048)
    output = tmp_path / "worker-output.mp4"
    job_json = tmp_path / "job.json"
    job_json.write_text(
        json.dumps(
            {
                "job_id": "job-1",
                "input_assets": [
                    {
                        "asset_id": "asset-1",
                        "kind": "source_video",
                        "file_name": "source.mp4",
                        "content_type": "video/mp4",
                        "local_path": str(source),
                    }
                ],
                "payload": {
                    "script": "测试口播文案",
                    "voice_id": "classic-female",
                    "bgm_id": "default-light",
                    "subtitle_enabled": True,
                    "source_file_name": "source.mp4",
                    "output_upload": {"url": "https://cos.example.com/output"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    server = _start_server(rendered)
    try:
        api_base = f"http://127.0.0.1:{server.server_port}"
        result = run_job(job_json=job_json, output_path=output, api_base=api_base)
    finally:
        server.shutdown()
        server.server_close()

    assert output.read_bytes() == rendered.read_bytes()
    assert result["mode"] == "local_render_api"
    assert result["task_id"] == "task-123"
    assert server.render_payload == {
        "script": "测试口播文案",
        "voice_id": "classic-female",
        "bgm_id": "default-light",
        "subtitle_enabled": True,
    }


def test_build_render_payload_filters_cloud_only_fields_and_uses_script_fallback():
    payload = build_render_payload(
        {
            "rewritten_script": "改写后的文案",
            "source_file_name": "source.mp4",
            "output_upload": {"url": "https://cos.example.com/output"},
            "voice_id": "classic-female",
            "subtitle_style": {"font_size": 42},
        }
    )

    assert payload == {
        "script": "改写后的文案",
        "voice_id": "classic-female",
        "subtitle_style": {"font_size": 42},
    }


def test_build_render_payload_keeps_composition_options():
    payload = build_render_payload(
        {
            "script": "成片文案",
            "voice_volume": 0.45,
            "bgm_id": "custom:bgm-1",
            "bgm_volume": 0.22,
            "subtitle_enabled": True,
            "pip_enabled": True,
            "pip_asset_id": "pip-1",
            "pip_position": "bottom_right",
            "pip_scale": 0.36,
            "pip_x": 0.1,
            "pip_y": 0.2,
            "pip_width": 0.36,
            "pip_height": 0.12,
            "pip_timing_mode": "sentence",
            "pip_trigger_text": "这里出现画中画",
            "cover_template_id": "bold-yellow-white",
            "subtitle_template_id": "renovation_pitfall_yellow",
            "template_catalog_version": "2026.07.15.1",
            "source_file_name": "source.mp4",
        }
    )

    assert payload["bgm_id"] == "custom:bgm-1"
    assert payload["voice_volume"] == 0.45
    assert payload["bgm_volume"] == 0.22
    assert payload["pip_enabled"] is True
    assert payload["pip_position"] == "bottom_right"
    assert payload["pip_scale"] == 0.36
    assert payload["pip_x"] == 0.1
    assert payload["pip_y"] == 0.2
    assert payload["pip_width"] == 0.36
    assert payload["pip_height"] == 0.12
    assert payload["pip_timing_mode"] == "sentence"
    assert payload["pip_trigger_text"] == "这里出现画中画"
    assert payload["cover_template_id"] == "bold-yellow-white"
    assert payload["subtitle_template_id"] == "renovation_pitfall_yellow"
    assert payload["template_catalog_version"] == "2026.07.15.1"


def test_deferred_packaging_forces_unity_voice_and_skips_final_composition():
    payload = build_render_payload(
        {
            "script": "先生成数字人中间视频",
            "defer_packaging": True,
            "voice_volume": 0.2,
            "bgm_id": "custom:bgm-1",
            "bgm_volume": 0.8,
            "subtitle_enabled": True,
            "pip_enabled": True,
        }
    )

    assert payload["voice_volume"] == 1.0
    assert payload["bgm_id"] == "none"
    assert payload["bgm_volume"] == 0
    assert payload["subtitle_enabled"] is False
    assert payload["pip_enabled"] is False
    assert should_compose_final(payload, None, None, None) is False


def test_cloud_subtitles_default_to_small_wrapped_captions():
    assert wrap_text("abcdefghijklmnopqr", 8) == ["abcdefgh\nijklmnop", "qr"]
    force_style = subtitle_force_style({})
    assert "FontSize=12" in force_style
    assert "Outline=2" in force_style
    assert "MarginV=70" in force_style
    assert wrap_text("開直播後臺觀眾", 20) == ["开直播后台观众"]


def test_cloud_subtitle_template_scales_from_portrait_design_canvas():
    force_style = subtitle_force_style(
        {
            "font_size": 64,
            "outline_width": 5,
            "margin_v": 390,
            "position": "middle",
            "design_height": 1920,
        }
    )

    assert "FontSize=9.6" in force_style
    assert "Outline=0.75" in force_style
    assert "MarginV=59" in force_style
    assert "Alignment=5" in force_style


def test_generate_srt_file_marks_last_line_with_keyword_color(tmp_path):
    output = tmp_path / "template.srt"

    generate_srt_file(
        "第一行第二行",
        {"max_chars_per_line": 3, "keyword_color": "#FFE23B"},
        output,
        2.0,
    )

    content = output.read_text(encoding="utf-8")
    assert '<font color="#FFE23B">第二行</font>' in content


def test_cloud_rewrite_prompt_constraint_stays_at_300_chars():
    assert bounded_rewrite_chars({"max_chars": 800}) == 300
    assert to_simplified_chinese("開直播後臺觀眾") == "开直播后台观众"


def test_prepare_cosyvoice_reference_converts_m4a_to_mono_16k_wav(monkeypatch, tmp_path):
    source = tmp_path / "reference.m4a"
    source.write_bytes(b"m4a-reference")
    output = tmp_path / "reference.wav"
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        with wave.open(str(output), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\0\0" * 160)
        return type("Completed", (), {"returncode": 0, "stderr": b""})()

    monkeypatch.setattr(run_render_module, "ffmpeg_executable", lambda: "ffmpeg")
    monkeypatch.setattr(run_render_module.subprocess, "run", fake_run)

    assert prepare_cosyvoice_reference_audio(source, output) == output
    command = commands[0]
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-ar") + 1] == "16000"
    assert command[command.index("-c:a") + 1] == "pcm_s16le"
    with wave.open(str(output), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getframerate() == 16000


def test_find_source_asset_prefers_source_video_kind(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    asset = find_source_asset(
        {
            "input_assets": [
                {"kind": "thumbnail", "file_name": "cover.png", "local_path": "cover.png"},
                {"kind": "source_video", "file_name": "source.mp4", "local_path": str(source)},
            ]
        }
    )

    assert asset["local_path"] == str(source)


def test_voice_reference_is_not_treated_as_generated_voice(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF" + b"\0" * 128)

    job = {
        "input_assets": [
            {
                "kind": "voice_reference",
                "file_name": "reference.wav",
                "content_type": "audio/wav",
                "local_path": str(reference),
            }
        ]
    }

    assert find_voice_audio_asset(job) is None
    assert find_voice_reference_asset(job)["local_path"] == str(reference)


def test_bgm_asset_is_not_treated_as_generated_voice(tmp_path):
    bgm = tmp_path / "bgm.mp3"
    bgm.write_bytes(b"ID3" + b"\0" * 128)
    job = {
        "input_assets": [
            {
                "kind": "bgm_audio",
                "file_name": "bgm.mp3",
                "content_type": "audio/mpeg",
                "local_path": str(bgm),
            }
        ]
    }

    assert find_voice_audio_asset(job) is None
    assert find_bgm_audio_asset(job)["local_path"] == str(bgm)


def test_find_pip_asset_by_kind(tmp_path):
    pip = tmp_path / "pip.png"
    pip.write_bytes(b"\x89PNG\r\n\x1a\n")
    job = {
        "input_assets": [
            {
                "kind": "pip_asset",
                "file_name": "pip.png",
                "content_type": "image/png",
                "local_path": str(pip),
            }
        ]
    }

    assert find_pip_asset(job)["local_path"] == str(pip)


def test_find_cover_asset_by_kind(tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"\x89PNG\r\n\x1a\n")
    job = {
        "input_assets": [
            {
                "kind": "thumbnail",
                "file_name": "cover.png",
                "content_type": "image/png",
                "local_path": str(cover),
            }
        ]
    }

    assert find_cover_asset(job)["local_path"] == str(cover)


def test_pip_sentence_timing_uses_audio_duration():
    payload = {
        "script": "第一句。第二句。第三句。",
        "subtitle_style": {"max_chars_per_line": 20},
        "pip_timing_mode": "sentence",
        "pip_trigger_text": "第二句",
    }

    assert pip_enable_expression(payload, duration_seconds=9) == "between(t\\,3.000\\,6.000)"


def test_compose_final_video_resets_pts_and_reports_pip(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    voice = tmp_path / "voice.wav"
    pip = tmp_path / "pip.jpg"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"video")
    voice.write_bytes(b"voice")
    pip.write_bytes(b"image")
    commands = []

    def fake_run(command, check=False):
        commands.append(command)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(run_render_module, "ffmpeg_executable", lambda: "ffmpeg")
    monkeypatch.setattr(run_render_module, "media_duration_seconds", lambda path: 20.0)
    monkeypatch.setattr(run_render_module, "media_video_dimensions", lambda path: (720, 1280))
    monkeypatch.setattr(run_render_module, "media_video_frame_rate", lambda path: "25")
    monkeypatch.setattr(run_render_module.subprocess, "run", fake_run)

    compose_final_video(
        source_video=source,
        voice_audio=voice,
        render_payload={
            "script": "test pip",
            "subtitle_enabled": False,
            "pip_enabled": True,
            "pip_position": "top_right",
            "pip_scale": 0.5,
            "pip_timing_mode": "time",
            "pip_start_seconds": 5,
            "pip_end_seconds": 10,
        },
        output_path=output,
        bgm_audio=None,
        pip_asset=pip,
    )

    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert "[1:a]volume=0.45[aout]" in filter_complex
    assert "loudnorm" not in filter_complex
    assert "[0:v]scale=720:1280:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[mainv]" in filter_complex
    assert "[2:v]scale=360:202:force_original_aspect_ratio=increase,crop=360:202,setsar=1,setpts=PTS-STARTPTS[pip]" in filter_complex
    assert "[mainv][pip]overlay=344:16:enable='between(t\\,5.000\\,10.000)':eof_action=pass" in filter_complex
    assert "enable='between(t\\,5.000\\,10.000)':eof_action=pass" in filter_complex
    assert "overlay=344:16" in filter_complex
    assert commands[0][commands[0].index("-crf") + 1] == "18"
    assert commands[0][commands[0].index("-r") + 1] == "25"
    assert compose_final_video.last_diagnostics["pip_composed"] is True


def test_compose_final_video_uses_custom_pip_rect(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    voice = tmp_path / "voice.wav"
    pip = tmp_path / "pip.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"video")
    voice.write_bytes(b"voice")
    pip.write_bytes(b"video")
    commands = []

    def fake_run(command, check=False):
        commands.append(command)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(run_render_module, "ffmpeg_executable", lambda: "ffmpeg")
    monkeypatch.setattr(run_render_module, "media_duration_seconds", lambda path: 20.0)
    monkeypatch.setattr(run_render_module, "media_video_dimensions", lambda path: (720, 1280))
    monkeypatch.setattr(run_render_module, "media_video_frame_rate", lambda path: "25")
    monkeypatch.setattr(run_render_module.subprocess, "run", fake_run)

    compose_final_video(
        source_video=source,
        voice_audio=voice,
        render_payload={
            "script": "test pip",
            "subtitle_enabled": False,
            "pip_enabled": True,
            "pip_position": "custom",
            "pip_x": 0.10,
            "pip_y": 0.20,
            "pip_width": 0.50,
            "pip_height": 0.20,
        },
        output_path=output,
        bgm_audio=None,
        pip_asset=pip,
    )

    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert "[2:v]scale=360:256:force_original_aspect_ratio=increase,crop=360:256,setsar=1,setpts=PTS-STARTPTS[pip]" in filter_complex
    assert "[mainv][pip]overlay=72:256:eof_action=pass" in filter_complex


def test_compose_final_video_places_cover_on_frame_zero_after_subtitles(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    voice = tmp_path / "voice.wav"
    cover = tmp_path / "cover.png"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"video")
    voice.write_bytes(b"voice")
    cover.write_bytes(b"image")
    commands = []

    def fake_run(command, check=False):
        commands.append(command)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(run_render_module, "ffmpeg_executable", lambda: "ffmpeg")
    monkeypatch.setattr(run_render_module, "media_duration_seconds", lambda path: 5.0)
    monkeypatch.setattr(run_render_module, "media_video_dimensions", lambda path: (720, 1280))
    monkeypatch.setattr(run_render_module, "media_video_frame_rate", lambda path: "25")
    monkeypatch.setattr(run_render_module.subprocess, "run", fake_run)

    compose_final_video(
        source_video=source,
        voice_audio=voice,
        render_payload={
            "script": "第一行第二行",
            "subtitle_enabled": True,
            "subtitle_style": {"max_chars_per_line": 3},
        },
        output_path=output,
        bgm_audio=None,
        pip_asset=None,
        cover_image=cover,
    )

    command = commands[0]
    filter_complex = command[command.index("-filter_complex") + 1]
    assert "subtitles=" in filter_complex
    assert "[2:v]scale=720:1280" in filter_complex
    assert "trim=end_frame=1" in filter_complex
    assert "[subv][coverv]overlay=0:0:enable='eq(n\\,0)'" in filter_complex
    assert compose_final_video.last_diagnostics["cover_composed"] is True


def test_preprocess_rewrite_can_return_placeholder_result(monkeypatch, tmp_path):
    monkeypatch.setenv("REWRITE_PROVIDER", "placeholder")
    result = run_preprocess_job(
        job={
            "job_id": "job-preprocess",
            "job_type": "preprocess",
            "payload": {
                "task_type": "preprocess",
                "operation": "rewrite",
                "source_script": "Hello 大家好 今天终于拍了第一条视频",
            },
        },
        output_path=tmp_path / "result.mp4",
    )

    assert result["operation"] == "rewrite"
    assert result["original_script"] == "Hello 大家好 今天终于拍了第一条视频"
    assert "哈喽" in result["rewritten_script"]
