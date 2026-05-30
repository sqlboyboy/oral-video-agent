from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_check():
    res = client.get("/api/health")

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_builtin_catalogs_are_available():
    voices = client.get("/api/voices")
    bgm = client.get("/api/bgm")

    assert voices.status_code == 200
    assert len(voices.json()["items"]) >= 1
    assert bgm.status_code == 200
    assert len(bgm.json()["items"]) >= 1


def test_link_task_rewrite_and_render_flow():
    created = client.post("/api/tasks", json={"douyin_url": "https://example.test/video"})
    assert created.status_code == 200
    task = created.json()
    assert task["status"] == "transcribed"
    assert task["original_script"]

    rewritten = client.post(
        f"/api/tasks/{task['task_id']}/rewrite",
        json={"style": "带货", "product_info": "智能口播软件", "target_audience": "短视频创作者"},
    )
    assert rewritten.status_code == 200
    rewritten_task = rewritten.json()
    assert rewritten_task["status"] == "rewritten"
    assert "智能口播软件" in rewritten_task["rewritten_script"]

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
