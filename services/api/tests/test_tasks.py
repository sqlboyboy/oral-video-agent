from pathlib import Path
from unittest.mock import patch
from functools import lru_cache
import io
import json
import subprocess
import tempfile
from uuid import uuid4
import wave

from fastapi.testclient import TestClient
import imageio_ffmpeg

from app import main as main_module
from app.main import app
from app.models import Asset, MouthQualitySignals, OralVideoTask, RenderOptions, SubtitleStyle, TaskStatus, VoiceProfile, storage_dir
from app.pipeline.renderer import Renderer
from app.providers.video_importer import VideoImportError, extract_douyin_share_url, extract_first_url
from app.repository import repo


client = TestClient(app)


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)
    return buffer.getvalue()


@lru_cache(maxsize=1)
def _mp4_bytes() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "source.mp4"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=320x240:d=1:r=25",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        return path.read_bytes()


# Helper: create a task via local video upload (avoids real network calls)
def _create_task_via_upload(filename: str = "source.mp4", title: str = None) -> dict:
    files = {"file": (filename, _mp4_bytes(), "video/mp4")}
    with patch("app.main.asr_provider.transcribe", return_value="测试转写文案"):
        res = client.post("/api/tasks/upload", files=files)
    assert res.status_code == 200
    task = res.json()
    if title:
        patched = client.patch(f"/api/tasks/{task['task_id']}", json={"title": title})
        assert patched.status_code == 200
        return patched.json()
    return task


def test_health_check():
    res = client.get("/api/health")

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_version_endpoint():
    res = client.get("/api/version")

    assert res.status_code == 200
    assert res.json() == {"name": "oral-video-agent-api", "version": "0.1.0"}


def test_bootstrap_catalog_returns_client_startup_data():
    res = client.get("/api/bootstrap")

    assert res.status_code == 200
    body = res.json()
    assert body["providers"]["rewrite_provider"] == "placeholder"
    assert body["voices"]
    assert body["bgm"]
    assert any(item["name"] == "同款口播" for item in body["rewrite_styles"])


def test_subtitle_style_defaults_to_first_template():
    style = SubtitleStyle()

    assert style.template_id == "renovation_pitfall_yellow"
    assert style.color == "#FFFFFF"
    assert style.outline_color == "#111111"


def test_task_subtitle_generation_writes_srt():
    task = _create_task_via_upload()

    generated = client.post(
        f"/api/tasks/{task['task_id']}/subtitles",
        json={
            "script": "第一句字幕。第二句字幕。",
            "voice_id": "classic-female",
            "subtitle_style": {
                "font_size": 42,
                "color": "#FFE600",
                "outline_color": "#000000",
                "position": "bottom",
                "max_chars_per_line": 8,
            },
        },
    )

    assert generated.status_code == 200
    body = generated.json()
    subtitle_path = Path(body["subtitle_path"])
    assert subtitle_path.exists()
    assert "第一句字幕" in subtitle_path.read_text(encoding="utf-8")
    assert body["render_options"]["subtitle_style"]["color"] == "#FFE600"


def test_renderer_subtitle_filter_uses_douyin_yellow_style(monkeypatch):
    monkeypatch.setattr("app.pipeline.renderer._ffmpeg_executable", lambda: "ffmpeg")
    options = RenderOptions(
        subtitle_style=SubtitleStyle(
            font_size=42,
            color="#FFE600",
            outline_color="#000000",
        )
    )

    command = Renderer().build_ffmpeg_command(
        Path("source.mp4"),
        Path("voice.wav"),
        Path("subtitle.srt"),
        options,
        Path("output.mp4"),
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "force_style=" in filter_complex
    assert "FontName=Microsoft YaHei" in filter_complex
    assert "PrimaryColour=&H0000E6FF&" in filter_complex
    assert "OutlineColour=&H00000000&" in filter_complex


def test_deferred_render_creates_unpacked_digital_human_video():
    task = _create_task_via_upload()

    rendered = client.post(
        f"/api/tasks/{task['task_id']}/render",
        json={
            "script": "先生成数字人中间视频，再选择封面、字幕和背景音乐。",
            "voice_id": "classic-female",
            "voice_volume": 0.2,
            "bgm_id": "default-light",
            "subtitle_enabled": True,
            "pip_enabled": True,
            "pip_asset_id": None,
            "cover_path": "not-applied.png",
            "defer_packaging": True,
        },
    )

    assert rendered.status_code == 200
    rendered_task = rendered.json()
    assert rendered_task["status"] == "completed"
    assert rendered_task["output_video_path"]
    assert rendered_task["subtitle_path"] is None
    assert rendered_task["cover_path"] is None
    assert rendered_task["render_options"]["defer_packaging"] is True
    assert rendered_task["render_options"]["voice_volume"] == 1.0
    assert rendered_task["render_options"]["bgm_id"] == "none"
    assert rendered_task["render_options"]["subtitle_enabled"] is False
    assert rendered_task["render_options"]["pip_enabled"] is False


def test_pip_upload_returns_asset():
    uploaded = client.post(
        "/api/pip/upload",
        files={"file": ("pip.png", b"pip-bytes", "image/png")},
    )

    assert uploaded.status_code == 200
    asset = uploaded.json()["asset"]
    assert asset["kind"] == "pip"
    assert asset["filename"] == "pip.png"


def test_renderer_pip_overlay_command(monkeypatch):
    monkeypatch.setattr("app.pipeline.renderer._ffmpeg_executable", lambda: "ffmpeg")
    options = RenderOptions(
        pip_enabled=True,
        pip_scale=0.25,
        pip_position="bottom_left",
    )

    command = Renderer().build_ffmpeg_command(
        Path("source.mp4"),
        Path("voice.wav"),
        None,
        options,
        Path("output.mp4"),
        pip_asset=Path("pip.png"),
    )

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "-loop" in command
    assert "[0:v]scale=1080:1920:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[mainv]" in filter_complex
    assert "scale=270:152:force_original_aspect_ratio=increase" in filter_complex
    assert "[mainv][pip]overlay=24:1744:eof_action=pass[basev]" in filter_complex


def test_rewrite_style_presets_are_available():
    res = client.get("/api/rewrite/styles")

    assert res.status_code == 200
    items = res.json()["items"]
    names = {item["name"] for item in items}
    assert {"同款口播", "带货", "知识口播", "种草", "情绪价值"}.issubset(names)


def test_provider_status_reports_default_placeholder_config():
    res = client.get("/api/providers")

    assert res.status_code == 200
    body = res.json()
    assert body["rewrite_provider"] == "placeholder"
    assert body["deepseek_model"] is None
    assert body["deepseek_configured"] is False
    assert body["asr_provider"] in ("placeholder", "faster-whisper")
    assert body["voice_provider"] == "placeholder"
    assert body["voice_configured"] is True
    assert body["wav2lip_blend_enabled"] is True
    assert body["wav2lip_blend_preset"] == "balanced"
    assert body["wav2lip_aperture_atlas_enabled"] is (
        body["wav2lip_blend_enabled"] and body["wav2lip_onnx_configured"]
    )
    assert body["wav2lip_aperture_atlas_source"] is None
    assert body["wav2lip_aperture_atlas_source_mode"] == "reference-video"
    assert body["wav2lip_aperture_atlas_strength"] == 0.5
    assert body["wav2lip_aperture_energy_threshold"] == 0.24
    assert body["wav2lip_aperture_min_ratio"] == 0.07
    assert body["wav2lip_aperture_max_ratio"] == 0.36
    assert body["wav2lip_aperture_attack"] == 1.0
    assert body["wav2lip_aperture_release"] == 1.0
    assert body["wav2lip_quality_diagnostics_enabled"] is True
    assert body["wav2lip_quality_diagnostics_sample_stride"] == 2
    assert body["wav2lip_quality_diagnostics_max_frames"] == 240


def test_digital_human_health_reports_mouth_aperture_config():
    res = client.get("/api/digital-human/health")

    assert res.status_code == 200
    mouth_aperture = res.json()["high_quality"]["mouth_aperture"]
    assert mouth_aperture["blend_enabled"] is True
    assert mouth_aperture["atlas_enabled"] is (
        mouth_aperture["blend_enabled"] and res.json()["high_quality"]["wav2lip_onnx_configured"]
    )
    assert mouth_aperture["atlas_source_mode"] == "reference-video"
    assert mouth_aperture["atlas_strength"] == 0.5
    assert mouth_aperture["energy_threshold"] == 0.24
    assert mouth_aperture["quality_diagnostics"] == {
        "enabled": True,
        "sample_stride": 2,
        "max_frames": 240,
    }


def test_builtin_catalogs_are_available():
    voices = client.get("/api/voices")
    bgm = client.get("/api/bgm")

    assert voices.status_code == 200
    assert len(voices.json()["items"]) >= 1
    assert bgm.status_code == 200
    assert len(bgm.json()["items"]) >= 1


def test_video_upload_rejects_unsupported_file_type():
    uploaded = client.post(
        "/api/tasks/upload",
        files={"file": ("source.txt", b"not-video", "text/plain")},
    )

    assert uploaded.status_code == 400
    assert "不支持的文件类型" in uploaded.json()["detail"]


def test_bgm_upload_rejects_unsupported_file_type():
    uploaded = client.post(
        "/api/bgm/upload",
        files={"file": ("bgm.txt", b"not-audio", "text/plain")},
    )

    assert uploaded.status_code == 400
    assert "不支持的文件类型" in uploaded.json()["detail"]


def test_video_upload_creates_source_asset_task():
    with patch("app.main.asr_provider.transcribe", return_value="测试转写文案"):
        uploaded = client.post(
            "/api/tasks/upload",
            files={"file": ("source.mp4", _mp4_bytes(), "video/mp4")},
        )

    assert uploaded.status_code == 200
    task = uploaded.json()
    assert task["status"] == "transcribed"
    assert task["source_video"]["kind"] == "source_video"
    assert task["source_video"]["filename"] == "source.mp4"
    assert task["source_video"]["asset_id"]
    assert task["original_script"]


def test_video_upload_transcribes_uploaded_file_path():
    with patch("app.main.asr_provider.transcribe", return_value="真实转写结果") as mock_transcribe:
        uploaded = client.post(
            "/api/tasks/upload",
            files={"file": ("source.mp4", _mp4_bytes(), "video/mp4")},
        )

    assert uploaded.status_code == 200
    task = uploaded.json()
    assert task["original_script"] == "真实转写结果"
    audio_path_arg, source_hint_arg = mock_transcribe.call_args.args
    assert audio_path_arg == Path(task["source_video"]["path"])
    assert source_hint_arg == "source.mp4"


def test_update_task_title():
    task = _create_task_via_upload()
    task_id = task["task_id"]

    updated = client.patch(f"/api/tasks/{task_id}", json={"title": "新标题"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "新标题"

    listed = client.get("/api/tasks")
    summary = next(item for item in listed.json()["items"] if item["task_id"] == task_id)
    assert summary["title"] == "新标题"


def test_delete_task_removes_generated_files():
    with patch("app.main.asr_provider.transcribe", return_value="测试转写文案"):
        uploaded = client.post(
            "/api/tasks/upload",
            files={"file": ("cleanup.mp4", _mp4_bytes(), "video/mp4")},
        )
    assert uploaded.status_code == 200
    task_id = uploaded.json()["task_id"]

    rendered = client.post(
        f"/api/tasks/{task_id}/render",
        json={"script": "清理测试", "voice_id": "classic-female", "bgm_id": "default-light"},
    )
    assert rendered.status_code == 200
    rendered_task = rendered.json()
    paths = [
        rendered_task["source_video"]["path"],
        rendered_task["extracted_audio_path"],
        rendered_task["subtitle_path"],
        rendered_task["output_video_path"],
        rendered_task["cover_path"],
    ]
    assert all(paths)

    deleted = client.delete(f"/api/tasks/{task_id}")
    assert deleted.status_code == 200

    for path in paths:
        assert not Path(path).exists()


def test_delete_task_removes_it_from_repository():
    task = _create_task_via_upload()
    task_id = task["task_id"]

    deleted = client.delete(f"/api/tasks/{task_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}

    missing = client.get(f"/api/tasks/{task_id}")
    assert missing.status_code == 404


def test_task_list_returns_summaries():
    task = _create_task_via_upload(title="列表测试")
    task_id = task["task_id"]

    listed = client.get("/api/tasks")
    assert listed.status_code == 200
    items = listed.json()["items"]
    summary = next(item for item in items if item["task_id"] == task_id)
    assert summary["task_id"] == task_id
    assert summary["title"] == "列表测试"
    assert summary["status"] == "transcribed"
    assert summary["output_ready"] is False


def test_mouth_quality_report_summarizes_internal_scores():
    ok_task = OralVideoTask(
        title="口型质量 OK",
        status=TaskStatus.completed,
        output_video_path="storage/outputs/ok.mp4",
        mouth_quality=MouthQualitySignals(
            verdict="ok",
            mouth_state_alignment_verdict="ok",
            low_energy_visible_gap_ratio=0.0,
            high_energy_muted_open_ratio=0.0,
            high_energy_mean_ratio=0.2873,
            vowel_muted_ratio=0.1667,
            vowel_mean_ratio=0.2649,
        ),
    )
    review_task = OralVideoTask(
        title="口型质量待复核",
        status=TaskStatus.completed,
        output_video_path="storage/outputs/review.mp4",
        mouth_quality=MouthQualitySignals(
            verdict="needs_review",
            mouth_state_alignment_verdict="needs_review",
            low_energy_visible_gap_ratio=0.35,
            high_energy_muted_open_ratio=0.5,
            high_energy_mean_ratio=0.21,
            vowel_muted_ratio=0.55,
            vowel_mean_ratio=0.22,
        ),
    )
    missing_task = OralVideoTask(title="缺少口型质量", status=TaskStatus.completed)
    for task in (ok_task, review_task, missing_task):
        repo.put(task)

    try:
        res = client.get("/api/tasks/mouth-quality")
        quality_only = client.get("/api/tasks/mouth-quality", params={"include_missing": False})
    finally:
        for task in (ok_task, review_task, missing_task):
            try:
                repo.delete(task.task_id)
            except KeyError:
                pass

    assert res.status_code == 200
    body = res.json()
    by_id = {item["task_id"]: item for item in body["items"]}
    assert by_id[ok_task.task_id]["grade"] == "ok"
    assert by_id[ok_task.task_id]["score"] >= 90
    assert by_id[review_task.task_id]["grade"] == "needs_review"
    assert by_id[review_task.task_id]["score"] < 70
    review_issues = {issue["code"] for issue in by_id[review_task.task_id]["issues"]}
    assert "closed_state_visible_gap" in review_issues
    assert "expected_vowel_muted" in review_issues
    assert by_id[missing_task.task_id]["grade"] == "missing"
    assert by_id[missing_task.task_id]["quality"] is None
    assert by_id[missing_task.task_id]["issues"][0]["code"] == "missing_quality"
    assert body["summary"]["grade_counts"]["ok"] >= 1
    assert body["summary"]["grade_counts"]["needs_review"] >= 1
    assert body["summary"]["grade_counts"]["missing"] >= 1
    assert body["summary"]["issue_counts"]["closed_state_visible_gap"] >= 1
    assert body["summary"]["hint_counts"]["increase_vowel_release_floor"] >= 1
    assert body["summary"]["metric_means"]["low_energy_visible_gap_ratio"] is not None

    assert quality_only.status_code == 200
    quality_items = {item["task_id"]: item for item in quality_only.json()["items"]}
    assert ok_task.task_id in quality_items
    assert review_task.task_id in quality_items
    assert missing_task.task_id not in quality_items


def test_extract_douyin_share_url_from_full_share_copy():
    samples = [
        (
            "2026，用智能体日更百条 https://v.douyin.com/q1e71qTpdU0/ 复制此链接，打开【抖音】，直接观看视频！",
            "https://v.douyin.com/q1e71qTpdU0/",
        ),
        (
            "还在为拍视频头疼吗？这个方法简单又方便～ #短视频创业 #实体商家  #引流拓客 #老板思维 https://v.douyin.com/NKaTns7EBKU/ 复制此链接，打开【抖音】，直接观看视频！",
            "https://v.douyin.com/NKaTns7EBKU/",
        ),
        (
            "8.97 :5pm 09/29 pdn:/ user@example.com 收入大揭秘，9.2万粉丝月入有多少？ # 自媒体收入  https://v.douyin.com/iLSGU9OilYU/ 复制此链接，打开Dou音搜索，直接观看视频！",
            "https://v.douyin.com/iLSGU9OilYU/",
        ),
    ]

    for share_text, expected_url in samples:
        assert extract_douyin_share_url(share_text) == expected_url
        assert extract_first_url(share_text) == expected_url


def test_extract_douyin_share_url_prefers_douyin_link_over_other_urls():
    share_text = "参考 https://example.com/a，再看 https://v.douyin.com/q1e71qTpdU0/ 复制此链接"

    assert extract_douyin_share_url(share_text) == "https://v.douyin.com/q1e71qTpdU0/"
    assert extract_first_url(share_text) == "https://v.douyin.com/q1e71qTpdU0/"


def test_extract_douyin_share_url_accepts_bare_domain_and_wrapped_punctuation():
    share_text = "爆款视频【v.douyin.com/q1e71qTpdU0/】复制打开抖音"

    assert extract_douyin_share_url(share_text) == "https://v.douyin.com/q1e71qTpdU0/"
    assert extract_first_url(share_text) == "https://v.douyin.com/q1e71qTpdU0/"


def test_extract_first_url_ignores_noisy_non_link_tokens_without_protocol():
    share_text = "8.97 :5pm 09/29 pdn:/ user@example.com 收入大揭秘"

    assert extract_douyin_share_url(share_text) is None
    assert extract_first_url(share_text) is None


def test_link_task_returns_failed_when_download_fails():
    """Pasting a Douyin share link that cannot be downloaded sets task status to failed."""
    with patch("app.main.video_importer.import_from_share_text",
               side_effect=VideoImportError("视频链接导入失败，请改用本地上传。原因：网络错误")):
        res = client.post("/api/tasks", json={"douyin_url": "https://v.douyin.com/fake"})

        assert res.status_code == 200
        task_id = res.json()["task_id"]

        # Link import runs in a background thread; keep the importer mock active while it settles.
        import time
        for _ in range(50):
            task = client.get(f"/api/tasks/{task_id}").json()
            if task["status"] in ("failed", "transcribed"):
                break
            time.sleep(0.1)

    assert task["status"] == "failed"
    assert "请改用本地上传" in task["error_message"]


def test_link_task_no_url_returns_failed():
    """Share text with no recognisable URL sets task status to failed."""
    with patch("app.main.video_importer.import_from_share_text",
               side_effect=VideoImportError("没有识别到有效视频链接")):
        res = client.post("/api/tasks", json={"douyin_url": "这是一段没有链接的文字"})

        assert res.status_code == 200
        task_id = res.json()["task_id"]

        import time
        for _ in range(10):
            task = client.get(f"/api/tasks/{task_id}").json()
            if task["status"] in ("failed", "transcribed"):
                break
            time.sleep(0.1)

    assert task["status"] == "failed"
    assert "没有识别到有效视频链接" in task["error_message"]


def test_link_task_reports_import_substeps():
    source_path = storage_dir("uploads") / f"{uuid4()}.mp4"
    source_path.write_bytes(b"fake-video")
    asset = Asset(kind="source_video", filename=source_path.name, path=str(source_path))
    share_url = f"https://v.douyin.com/{uuid4().hex}/"

    def fake_import(share_text, on_stage=None):
        if on_stage:
            on_stage("resolve_link", "running")
            on_stage("resolve_link", "completed")
            on_stage("download_video", "running")
            on_stage("download_video", "completed")
        return asset

    with patch("app.main.video_importer.import_from_share_text", side_effect=fake_import), \
         patch("app.main.asr_provider.transcribe", return_value="链接识别文案"):
        res = client.post("/api/tasks", json={"douyin_url": share_url})
        assert res.status_code == 200
        task_id = res.json()["task_id"]

        import time
        for _ in range(20):
            task = client.get(f"/api/tasks/{task_id}").json()
            if task["status"] in ("failed", "transcribed"):
                break
            time.sleep(0.1)

    progress = {step["key"]: step["status"] for step in task["progress_steps"]}
    assert task["status"] == "transcribed"
    assert task["original_script"] == "链接识别文案"
    assert progress["resolve_link"] == "completed"
    assert progress["download_video"] == "completed"
    assert progress["transcribe"] == "completed"
    assert progress["extract"] == "completed"


def test_link_task_reuses_cached_transcript():
    source_path = storage_dir("uploads") / f"{uuid4()}.mp4"
    source_path.write_bytes(b"cached-video")
    share_url = f"https://v.douyin.com/{uuid4().hex}/"
    cached = OralVideoTask(
        douyin_url=share_url,
        status=TaskStatus.transcribed,
        source_video=Asset(kind="source_video", filename=source_path.name, path=str(source_path)),
        original_script="缓存文案",
    )
    repo.put(cached)

    with patch("app.main.video_importer.import_from_share_text") as importer:
        res = client.post("/api/tasks", json={"douyin_url": f"复制打开 {share_url} 观看"})

    assert res.status_code == 200
    body = res.json()
    progress = {step["key"]: step["status"] for step in body["progress_steps"]}
    importer.assert_not_called()
    assert body["status"] == "transcribed"
    assert body["original_script"] == "缓存文案"
    assert progress["resolve_link"] == "completed"
    assert progress["download_video"] == "completed"
    assert progress["transcribe"] == "completed"


def test_upload_rewrite_and_render_flow():
    task = _create_task_via_upload()
    assert task["status"] == "transcribed"
    assert task["original_script"]
    assert task["progress_steps"][0] == {"key": "extract", "label": "1. 对标文案提取", "status": "completed"}

    rewritten = client.post(
        f"/api/tasks/{task['task_id']}/rewrite",
        json={"style": "带货", "product_info": "智能口播软件", "target_audience": "短视频创作者"},
    )
    assert rewritten.status_code == 200
    rewritten_task = rewritten.json()
    assert rewritten_task["status"] == "rewritten"
    assert rewritten_task["rewritten_script"]
    assert len(rewritten_task["rewritten_script"]) <= max(80, int(len(task["original_script"]) * 1.6))
    rewritten_progress = {step["key"]: step["status"] for step in rewritten_task["progress_steps"]}
    assert rewritten_progress["rewrite"] == "completed"

    rendered = client.post(
        f"/api/tasks/{task['task_id']}/render",
        json={
            "script": rewritten_task["rewritten_script"],
            "voice_id": "classic-female",
            "bgm_id": "default-light",
            "bgm_volume": 0.2,
            "subtitle_style": {
                "font_size": 42,
                "color": "#FFFFFF",
                "outline_color": "#000000",
                "position": "bottom",
                "max_chars_per_line": 18,
            },
        },
    )
    assert rendered.status_code == 200
    rendered_task = rendered.json()
    assert rendered_task["status"] == "completed"
    assert rendered_task["subtitle_path"]
    assert rendered_task["output_video_path"]
    assert rendered_task["video_title"]
    assert rendered_task["cover_path"]
    assert Path(rendered_task["cover_path"]).exists()
    progress_by_key = {step["key"]: step["status"] for step in rendered_task["progress_steps"]}
    assert progress_by_key["voice"] == "completed"
    assert progress_by_key["subtitle"] == "completed"
    assert progress_by_key["bgm"] == "completed"
    assert progress_by_key["digital_human"] == "completed"
    assert progress_by_key["title"] == "completed"
    assert progress_by_key["cover"] == "completed"


def test_render_records_internal_mouth_quality_artifacts():
    task = _create_task_via_upload()
    diagnosis_payload = {
        "verdict": "ok",
        "low_energy_visible_gap_ratio": 0.0,
        "high_energy_muted_open_ratio": 0.0,
        "high_energy_mean_ratio": 0.2873,
        "mouth_state_alignment": {
            "verdict": "ok",
            "vowel_muted_ratio": 0.1667,
            "vowel_mean_ratio": 0.2649,
        },
    }

    def fake_digital_human_render(**kwargs):
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"\x00\x00\x00\x18ftypmp42digital")
        output_path.with_suffix(".mouth_state.json").write_text(
            json.dumps({"frames": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        output_path.with_suffix(".mouth_diagnosis.json").write_text(
            json.dumps(diagnosis_payload, ensure_ascii=False),
            encoding="utf-8",
        )
        return output_path

    def fake_final_render(*args, **kwargs):
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"\x00\x00\x00\x18ftypmp42final")
        return output_path

    with patch("app.main.digital_human_provider.render", side_effect=fake_digital_human_render), \
            patch("app.main.renderer.render", side_effect=fake_final_render), \
            patch("app.main.is_playable_mp4", return_value=True):
        rendered = client.post(
            f"/api/tasks/{task['task_id']}/render",
            json={"script": "内部口型质量信号测试", "voice_id": "classic-female", "bgm_id": "default-light"},
        )

    assert rendered.status_code == 200
    rendered_task = rendered.json()
    quality = rendered_task["mouth_quality"]
    assert quality["verdict"] == "ok"
    assert quality["mouth_state_alignment_verdict"] == "ok"
    assert quality["low_energy_visible_gap_ratio"] == 0.0
    assert quality["high_energy_muted_open_ratio"] == 0.0
    assert quality["high_energy_mean_ratio"] == 0.2873
    assert quality["vowel_muted_ratio"] == 0.1667
    assert quality["vowel_mean_ratio"] == 0.2649
    assert quality["mouth_state_path"].endswith("_digital.mouth_state.json")
    assert quality["mouth_diagnosis_path"].endswith("_digital.mouth_diagnosis.json")
    assert Path(quality["mouth_state_path"]).exists()
    assert Path(quality["mouth_diagnosis_path"]).exists()


def test_delete_task_removes_internal_mouth_quality_artifacts():
    task = _create_task_via_upload()
    sidecars = {}

    def fake_digital_human_render(**kwargs):
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"\x00\x00\x00\x18ftypmp42digital")
        state_path = output_path.with_suffix(".mouth_state.json")
        diagnosis_path = output_path.with_suffix(".mouth_diagnosis.json")
        state_path.write_text(json.dumps({"frames": []}), encoding="utf-8")
        diagnosis_path.write_text(json.dumps({"verdict": "ok"}), encoding="utf-8")
        sidecars["state"] = state_path
        sidecars["diagnosis"] = diagnosis_path
        return output_path

    def fake_final_render(*args, **kwargs):
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"\x00\x00\x00\x18ftypmp42final")
        return output_path

    with patch("app.main.digital_human_provider.render", side_effect=fake_digital_human_render), \
            patch("app.main.renderer.render", side_effect=fake_final_render), \
            patch("app.main.is_playable_mp4", return_value=True):
        rendered = client.post(
            f"/api/tasks/{task['task_id']}/render",
            json={"script": "删除内部质量信号测试", "voice_id": "classic-female", "bgm_id": "default-light"},
        )

    assert rendered.status_code == 200
    assert sidecars["state"].exists()
    assert sidecars["diagnosis"].exists()

    deleted = client.delete(f"/api/tasks/{task['task_id']}")

    assert deleted.status_code == 200
    assert not sidecars["state"].exists()
    assert not sidecars["diagnosis"].exists()


def test_title_cover_and_publish_endpoints():
    task = _create_task_via_upload()
    task_id = task["task_id"]

    rewritten = client.post(
        f"/api/tasks/{task_id}/rewrite",
        json={"style": "同款口播", "source_script": "第一条口播视频，一百天见证成长。"},
    )
    assert rewritten.status_code == 200

    titled = client.post(f"/api/tasks/{task_id}/title")
    assert titled.status_code == 200
    titled_task = titled.json()
    assert titled_task["video_title"]
    assert titled_task["title"] == titled_task["video_title"]

    covered = client.post(f"/api/tasks/{task_id}/cover")
    assert covered.status_code == 200
    covered_task = covered.json()
    assert covered_task["cover_path"]
    assert Path(covered_task["cover_path"]).exists()

    cover = client.get(f"/api/tasks/{task_id}/cover")
    assert cover.status_code == 200
    assert cover.headers["content-type"].startswith("image/png")

    published = client.post(
        f"/api/tasks/{task_id}/publish",
        json={"platforms": ["douyin", "xiaohongshu"]},
    )
    assert published.status_code == 200
    assert set(published.json()["publish_results"]) == {"douyin", "xiaohongshu"}


def test_placeholder_rewrite_uses_original_script_content():
    with patch(
        "app.main.asr_provider.transcribe",
        return_value="开口总是抓不住重点，客户听完还是不知道你能解决什么问题。后来我把表达拆成痛点、方案、结果三段，转化明显高了。",
    ):
        uploaded = client.post(
            "/api/tasks/upload",
            files={"file": ("source.mp4", _mp4_bytes(), "video/mp4")},
        )

    assert uploaded.status_code == 200
    task = uploaded.json()

    rewritten = client.post(
        f"/api/tasks/{task['task_id']}/rewrite",
        json={"style": "同款口播", "product_info": "表达训练服务", "target_audience": "创业者"},
    )

    assert rewritten.status_code == 200
    rewritten_script = rewritten.json()["rewritten_script"]
    assert "抓不住重点" in rewritten_script
    assert "解决什么问题" in rewritten_script
    assert len(rewritten_script) <= int(len(task["original_script"]) * 1.35)


def test_rewrite_uses_edited_source_script_from_client():
    task = _create_task_via_upload()

    rewritten = client.post(
        f"/api/tasks/{task['task_id']}/rewrite",
        json={
            "style": "同款口播",
            "source_script": "这是用户在口播转文字框里手动修正后的内容，重点是连续一百天见证成长。",
            "product_info": "成长记录服务",
            "target_audience": "新手创作者",
        },
    )

    assert rewritten.status_code == 200
    rewritten_task = rewritten.json()
    assert rewritten_task["original_script"] == "这是用户在口播转文字框里手动修正后的内容，重点是连续一百天见证成长。"
    assert "连续一百天见证成长" in rewritten_task["rewritten_script"]
    assert len(rewritten_task["rewritten_script"]) <= int(len(rewritten_task["original_script"]) * 1.35)


def test_rewrite_keeps_short_script_close_to_original_length():
    task = _create_task_via_upload()
    source = "Hello 大家好今天终于鼓足勇气拍了第一条视频 很荣幸第一条视频就被你刷到希望你能给我点个关注给我一点鼓励吧谢谢"

    rewritten = client.post(
        f"/api/tasks/{task['task_id']}/rewrite",
        json={"style": "同款口播", "source_script": source, "product_info": "智能口播软件"},
    )

    assert rewritten.status_code == 200
    script = rewritten.json()["rewritten_script"]
    assert "产品名称" not in script
    assert "核心卖点" not in script
    assert "智能口播软件" not in script
    assert "关注" in script
    assert len(script) <= int(len(source) * 1.35)


def test_rewrite_requires_completed_transcription():
    created = client.post("/api/tasks", json={})
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    rewritten = client.post(
        f"/api/tasks/{task_id}/rewrite",
        json={"style": "同款口播", "product_info": "测试产品", "target_audience": "测试用户"},
    )

    assert rewritten.status_code == 409
    assert rewritten.json()["detail"] == "请先等待解析口播完成再进行仿写"


def test_delete_asset_removes_file_and_catalog_entry():
    uploaded = client.post(
        "/api/bgm/upload",
        files={"file": ("delete-bgm.mp3", b"delete-bytes", "audio/mpeg")},
    )
    assert uploaded.status_code == 200
    asset = uploaded.json()["asset"]
    asset_id = asset["asset_id"]
    assert Path(asset["path"]).exists()

    deleted = client.delete(f"/api/assets/{asset_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert not Path(asset["path"]).exists()

    downloaded = client.get(f"/api/assets/{asset_id}/download")
    assert downloaded.status_code == 404


def test_asset_download_returns_uploaded_file():
    uploaded = client.post(
        "/api/bgm/upload",
        files={"file": ("download-bgm.mp3", b"download-bytes", "audio/mpeg")},
    )
    assert uploaded.status_code == 200
    asset_id = uploaded.json()["asset"]["asset_id"]

    downloaded = client.get(f"/api/assets/{asset_id}/download")

    assert downloaded.status_code == 200
    assert downloaded.content == b"download-bytes"


def test_custom_voice_and_bgm_uploads_are_listed():
    voice_upload = client.post(
        "/api/voices/upload",
        files={"file": ("my-voice.wav", _wav_bytes(), "audio/wav")},
    )
    assert voice_upload.status_code == 200
    uploaded_voice = voice_upload.json()["voice"]
    assert uploaded_voice["built_in"] is False
    assert uploaded_voice["voice_id"].startswith("custom:")

    voices = client.get("/api/voices")
    assert voices.status_code == 200
    assert any(item["voice_id"] == uploaded_voice["voice_id"] for item in voices.json()["items"])

    bgm_upload = client.post(
        "/api/bgm/upload",
        files={"file": ("my-bgm.mp3", b"bgm-bytes", "audio/mpeg")},
    )
    assert bgm_upload.status_code == 200
    uploaded_bgm = bgm_upload.json()["bgm"]
    assert uploaded_bgm["built_in"] is False
    assert uploaded_bgm["bgm_id"].startswith("custom:")

    bgm = client.get("/api/bgm")
    assert bgm.status_code == 200
    assert any(item["bgm_id"] == uploaded_bgm["bgm_id"] for item in bgm.json()["items"])


def test_voice_reference_rejects_files_longer_than_three_minutes(monkeypatch):
    monkeypatch.setattr(main_module, "media_duration_seconds", lambda _path: 181.0)

    response = client.post(
        "/api/voices/upload",
        files={"file": ("too-long.wav", _wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "声音参考文件最长不能超过 3 分钟"


def test_voice_reference_up_to_three_minutes_is_allowed(monkeypatch):
    monkeypatch.setattr(main_module, "media_duration_seconds", lambda _path: 180.0)

    response = client.post(
        "/api/voices/upload",
        files={"file": ("three-minutes.wav", _wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200


def test_voice_reference_shorter_than_fifteen_seconds_is_allowed(monkeypatch):
    monkeypatch.setattr(main_module, "media_duration_seconds", lambda _path: 5.0)

    response = client.post(
        "/api/voices/upload",
        files={"file": ("short.wav", _wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200


def test_voice_preview_returns_uploaded_voice_reference():
    voice_upload = client.post(
        "/api/voices/upload",
        files={"file": ("preview-voice.wav", _wav_bytes(), "audio/wav")},
    )
    assert voice_upload.status_code == 200
    voice_id = voice_upload.json()["voice"]["voice_id"]

    preview = client.get("/api/voices/preview", params={"voice_id": voice_id})

    assert preview.status_code == 200
    assert preview.content.startswith(b"RIFF")


def test_clone_voice_preview_returns_template_file(tmp_path, monkeypatch):
    template = tmp_path / "标准男声.wav"
    template.write_bytes(_wav_bytes())
    monkeypatch.setattr(main_module, "clone_voice_templates_dir", lambda: tmp_path)

    preview = client.get(
        "/api/voices/preview",
        params={"voice_id": f"clone:{template.name}"},
    )

    assert preview.status_code == 200
    assert preview.content.startswith(b"RIFF")


def test_clone_folder_voice_templates_are_listed_first(tmp_path, monkeypatch):
    (tmp_path / "标准男声.m4a").write_bytes(b"voice")
    (tmp_path / "元气女生.m4a").write_bytes(b"voice")
    monkeypatch.setattr(main_module, "clone_voice_templates_dir", lambda: tmp_path)
    monkeypatch.setattr(main_module.asset_store, "list", lambda kind=None: [])

    catalog = main_module.build_voice_catalog()

    assert [item.voice_id for item in catalog["items"][:2]] == [
        "clone:标准男声.m4a",
        "clone:元气女生.m4a",
    ]
    assert [item.name for item in catalog["items"][:2]] == ["标准男声", "元气女生"]


def test_bgm_folder_templates_use_file_names(tmp_path, monkeypatch):
    (tmp_path / "宣传类口播.mp3").write_bytes(b"bgm")
    (tmp_path / "通用类口播.mp3").write_bytes(b"bgm")
    monkeypatch.setattr(main_module, "bgm_templates_dir", lambda: tmp_path)
    monkeypatch.setattr(main_module.asset_store, "list", lambda kind=None: [])

    catalog = main_module.build_bgm_catalog()

    assert [item.bgm_id for item in catalog["items"]] == [
        "template:宣传类口播.mp3",
        "template:通用类口播.mp3",
    ]
    assert [item.name for item in catalog["items"]] == ["宣传类口播", "通用类口播"]
    assert main_module.resolve_bgm_audio("template:宣传类口播.mp3") == tmp_path / "宣传类口播.mp3"


def test_recent_custom_items_keeps_ten_recent_unique(monkeypatch):
    profiles = [
        VoiceProfile(
            voice_id=f"custom:voice-{index}",
            name=f"voice-{index}",
            description="test voice",
            built_in=False,
        )
        for index in range(12)
    ]
    profiles.append(profiles[-1].model_copy())
    monkeypatch.setattr(
        main_module,
        "_load_recent_usage",
        lambda: {
            "voice": [
                {
                    "id": f"custom:voice-{index}",
                    "used_at": f"2026-06-28T00:{index:02d}:00+00:00",
                }
                for index in range(12)
            ]
        },
    )
    monkeypatch.setattr(main_module, "_fallback_usage_order", lambda kind: {})

    result = main_module._recent_custom_items("voice", profiles)

    assert [item.voice_id for item in result] == [
        f"custom:voice-{index}" for index in range(11, 1, -1)
    ]


def test_voice_reference_accepts_video_file():
    voice_upload = client.post(
        "/api/voices/upload",
        files={"file": ("voice-ref.mp4", b"voice-video-bytes", "video/mp4")},
    )

    assert voice_upload.status_code == 200
    uploaded_voice = voice_upload.json()["voice"]
    assert uploaded_voice["voice_id"].startswith("custom:")


def test_digital_human_upload_list_and_delete():
    uploaded = client.post(
        "/api/digital-humans/upload",
        files={"file": ("human-ref.mp4", b"human-video-bytes" * 128, "video/mp4")},
    )

    assert uploaded.status_code == 200
    asset = uploaded.json()["asset"]
    profile = uploaded.json()["digital_human"]
    assert profile["digital_human_id"].startswith("custom:")
    assert profile["thumbnail_url"].startswith("/api/digital-humans/thumbnail")

    listed = client.get("/api/digital-humans")
    assert listed.status_code == 200
    listed_profile = next(
        item
        for item in listed.json()["items"]
        if item["digital_human_id"] == profile["digital_human_id"]
    )
    assert listed_profile["thumbnail_url"].startswith("/api/digital-humans/thumbnail")

    deleted = client.delete(f"/api/assets/{asset['asset_id']}")
    assert deleted.status_code == 200
    assert not Path(asset["path"]).exists()


def test_digital_human_catalog_hides_system_templates_from_client(tmp_path, monkeypatch):
    for index in range(6):
        (tmp_path / f"template-{index}.mp4").write_bytes(b"video")
    monkeypatch.setattr(main_module, "digital_human_templates_dir", lambda: tmp_path)
    monkeypatch.setattr(main_module.asset_store, "list", lambda kind=None: [])
    monkeypatch.setattr(main_module, "_load_recent_usage", lambda: {})
    monkeypatch.setattr(main_module, "_fallback_usage_order", lambda kind: {})

    catalog = main_module.build_digital_human_catalog()

    assert catalog["items"] == []


def test_digital_human_atlas_diagnosis_requires_selection():
    diagnosed = client.get("/api/digital-humans/atlas-diagnosis", params={"digital_human_id": ""})

    assert diagnosed.status_code == 400


def test_digital_human_atlas_diagnosis_returns_reference_coverage():
    uploaded = client.post(
        "/api/digital-humans/upload",
        files={"file": ("human-atlas.mp4", b"human-video-bytes", "video/mp4")},
    )
    assert uploaded.status_code == 200
    digital_human_id = uploaded.json()["digital_human"]["digital_human_id"]

    with patch("tools.diagnose_mouth_naturalness.analyze_atlas_video") as mock_analyze:
        mock_analyze.return_value = {
            "verdict": "needs_better_reference",
            "coverage": {"usable_closed_count": 0},
            "warnings": ["Reference video lacks reliable closed-mouth frames."],
        }
        diagnosed = client.get(
            "/api/digital-humans/atlas-diagnosis",
            params={"digital_human_id": digital_human_id},
        )

    assert diagnosed.status_code == 200
    assert diagnosed.json()["verdict"] == "needs_better_reference"
    assert mock_analyze.call_args.args[0] == Path(uploaded.json()["asset"]["path"])
    assert mock_analyze.call_args.kwargs == {"sample_stride": 2, "max_frames": 240}


def test_render_accepts_uploaded_custom_bgm():
    task = _create_task_via_upload()

    bgm_upload = client.post(
        "/api/bgm/upload",
        files={"file": ("render-bgm.wav", _wav_bytes(), "audio/wav")},
    )
    assert bgm_upload.status_code == 200
    custom_bgm_id = bgm_upload.json()["bgm"]["bgm_id"]

    rendered = client.post(
        f"/api/tasks/{task['task_id']}/render",
        json={"script": "使用自定义背景音乐合成", "voice_id": "classic-female", "bgm_id": custom_bgm_id},
    )

    assert rendered.status_code == 200
    rendered_task = rendered.json()
    assert rendered_task["status"] == "completed"
    assert rendered_task["render_options"]["bgm_id"] == custom_bgm_id


def test_render_rejects_missing_custom_bgm():
    task = _create_task_via_upload()

    rendered = client.post(
        f"/api/tasks/{task['task_id']}/render",
        json={"script": "测试", "voice_id": "classic-female", "bgm_id": "custom:missing"},
    )

    assert rendered.status_code == 404
    assert rendered.json()["detail"] == "自定义素材不存在"


def test_output_endpoint_reports_readiness_before_and_after_render():
    task = _create_task_via_upload()
    task_id = task["task_id"]

    before = client.get(f"/api/tasks/{task_id}/output")
    assert before.status_code == 200
    assert before.json()["ready"] is False
    assert before.json()["path"] is None

    rendered = client.post(
        f"/api/tasks/{task_id}/render",
        json={"script": "生成成品文件", "voice_id": "classic-female", "bgm_id": "default-light"},
    )
    assert rendered.status_code == 200

    after = client.get(f"/api/tasks/{task_id}/output")
    assert after.status_code == 200
    body = after.json()
    assert body["ready"] is True
    assert body["path"]
    assert body["size_bytes"] > 0
    assert body["detail"] is None


def test_render_requires_script():
    created = client.post("/api/tasks", json={})
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    rendered = client.post(
        f"/api/tasks/{task_id}/render",
        json={"voice_id": "classic-female", "bgm_id": "default-light"},
    )

    assert rendered.status_code == 400
    assert rendered.json()["detail"] == "没有可合成的文案"
