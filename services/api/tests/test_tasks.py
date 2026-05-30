from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_check():
    res = client.get("/api/health")

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


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
    assert body["anthropic_model"] is None
    assert body["anthropic_configured"] is False
    assert body["asr_provider"] == "placeholder"
    assert body["whisper_model"] is None
    assert body["voice_provider"] == "placeholder"
    assert body["voice_configured"] is True


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
    uploaded = client.post(
        "/api/tasks/upload",
        files={"file": ("source.mp4", b"video-bytes", "video/mp4")},
    )

    assert uploaded.status_code == 200
    task = uploaded.json()
    assert task["status"] == "transcribed"
    assert task["source_video"]["kind"] == "source_video"
    assert task["source_video"]["filename"] == "source.mp4"
    assert task["source_video"]["asset_id"]
    assert task["original_script"]


def test_delete_task_removes_generated_files():
    uploaded = client.post(
        "/api/tasks/upload",
        files={"file": ("cleanup.mp4", b"video-bytes", "video/mp4")},
    )
    assert uploaded.status_code == 200
    task_id = uploaded.json()["task_id"]

    rendered = client.post(
        f"/api/tasks/{task_id}/render",
        json={"script": "清理测试", "voice_id": "default-female", "bgm_id": "default-light"},
    )
    assert rendered.status_code == 200
    rendered_task = rendered.json()
    paths = [
        rendered_task["source_video"]["path"],
        rendered_task["extracted_audio_path"],
        rendered_task["subtitle_path"],
        rendered_task["output_video_path"],
    ]
    assert all(paths)

    deleted = client.delete(f"/api/tasks/{task_id}")
    assert deleted.status_code == 200

    for path in paths:
        assert not Path(path).exists()


def test_delete_task_removes_it_from_repository():
    created = client.post("/api/tasks", json={"douyin_url": "https://example.test/delete-video"})
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    deleted = client.delete(f"/api/tasks/{task_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}

    missing = client.get(f"/api/tasks/{task_id}")
    assert missing.status_code == 404


def test_task_list_returns_summaries():
    created = client.post("/api/tasks", json={"douyin_url": "https://example.test/list-video", "title": "列表测试"})
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    listed = client.get("/api/tasks")
    assert listed.status_code == 200
    items = listed.json()["items"]
    summary = next(item for item in items if item["task_id"] == task_id)
    assert summary == {
        "task_id": task_id,
        "title": "列表测试",
        "status": "transcribed",
        "douyin_url": "https://example.test/list-video",
        "output_ready": False,
    }


def test_link_task_rewrite_and_render_flow():
    created = client.post("/api/tasks", json={"douyin_url": "https://example.test/video"})
    assert created.status_code == 200
    task = created.json()
    assert task["status"] == "transcribed"
    assert task["original_script"]
    assert task["progress_steps"][0] == {"key": "import", "label": "导入视频", "status": "completed"}
    assert task["progress_steps"][1] == {"key": "transcribe", "label": "解析口播", "status": "completed"}

    rewritten = client.post(
        f"/api/tasks/{task['task_id']}/rewrite",
        json={"style": "带货", "product_info": "智能口播软件", "target_audience": "短视频创作者"},
    )
    assert rewritten.status_code == 200
    rewritten_task = rewritten.json()
    assert rewritten_task["status"] == "rewritten"
    assert "智能口播软件" in rewritten_task["rewritten_script"]
    assert rewritten_task["progress_steps"][2]["status"] == "completed"

    rendered = client.post(
        f"/api/tasks/{task['task_id']}/render",
        json={
            "script": rewritten_task["rewritten_script"],
            "voice_id": "default-female",
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
    progress_by_key = {step["key"]: step["status"] for step in rendered_task["progress_steps"]}
    assert progress_by_key["voice"] == "completed"
    assert progress_by_key["subtitle"] == "completed"
    assert progress_by_key["render"] == "completed"


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
        files={"file": ("my-voice.wav", b"voice-bytes", "audio/wav")},
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


def test_render_accepts_uploaded_custom_bgm():
    created = client.post("/api/tasks", json={"douyin_url": "https://example.test/video"})
    assert created.status_code == 200
    task = created.json()

    bgm_upload = client.post(
        "/api/bgm/upload",
        files={"file": ("render-bgm.mp3", b"bgm-bytes", "audio/mpeg")},
    )
    assert bgm_upload.status_code == 200
    custom_bgm_id = bgm_upload.json()["bgm"]["bgm_id"]

    rendered = client.post(
        f"/api/tasks/{task['task_id']}/render",
        json={"script": "使用自定义背景音乐合成", "voice_id": "default-female", "bgm_id": custom_bgm_id},
    )

    assert rendered.status_code == 200
    rendered_task = rendered.json()
    assert rendered_task["status"] == "completed"
    assert rendered_task["render_options"]["bgm_id"] == custom_bgm_id


def test_render_rejects_missing_custom_bgm():
    created = client.post("/api/tasks", json={"douyin_url": "https://example.test/video"})
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    rendered = client.post(
        f"/api/tasks/{task_id}/render",
        json={"script": "测试", "voice_id": "default-female", "bgm_id": "custom:missing"},
    )

    assert rendered.status_code == 404
    assert rendered.json()["detail"] == "自定义素材不存在"


def test_output_endpoint_reports_readiness_before_and_after_render():
    created = client.post("/api/tasks", json={"douyin_url": "https://example.test/video"})
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    before = client.get(f"/api/tasks/{task_id}/output")
    assert before.status_code == 200
    assert before.json() == {"ready": False, "path": None, "size_bytes": 0}

    rendered = client.post(
        f"/api/tasks/{task_id}/render",
        json={"script": "生成成品文件", "voice_id": "default-female", "bgm_id": "default-light"},
    )
    assert rendered.status_code == 200

    after = client.get(f"/api/tasks/{task_id}/output")
    assert after.status_code == 200
    body = after.json()
    assert body["ready"] is True
    assert body["path"]
    assert body["size_bytes"] > 0


def test_render_requires_script():
    created = client.post("/api/tasks", json={})
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    rendered = client.post(
        f"/api/tasks/{task_id}/render",
        json={"voice_id": "default-female", "bgm_id": "default-light"},
    )

    assert rendered.status_code == 400
    assert rendered.json()["detail"] == "没有可合成的文案"
