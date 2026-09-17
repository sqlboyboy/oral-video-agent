import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the packaged app home first, then fall back to the api service root.
_packaged_home = os.getenv("ORAL_VIDEO_AGENT_HOME")
if _packaged_home:
    load_dotenv(Path(_packaged_home) / ".env", override=True, encoding="utf-8-sig")
load_dotenv(Path(__file__).parent.parent / ".env", encoding="utf-8-sig")


@dataclass(frozen=True)
class Settings:
    rewrite_provider: str = os.getenv("REWRITE_PROVIDER", "deepseek")
    deepseek_api_key: str | None = os.getenv("DEEPSEEK_API_KEY")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    deepseek_timeout_seconds: int = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "240"))
    asr_provider: str = os.getenv("ASR_PROVIDER", "placeholder")
    whisper_model: str = os.getenv("WHISPER_MODEL", "small")
    voice_provider: str = os.getenv("VOICE_PROVIDER", "placeholder")
    voice_clone_command: str | None = os.getenv("VOICE_CLONE_COMMAND")
    voice_base_url: str = os.getenv("VOICE_BASE_URL", "http://127.0.0.1:16010")
    voice_timeout_seconds: int = int(os.getenv("VOICE_TIMEOUT_SECONDS", "1800"))
    tts_api_key: str | None = os.getenv("TTS_API_KEY")
    digital_human_provider: str = os.getenv("DIGITAL_HUMAN_PROVIDER", "heygem-local")
    digital_human_command: str | None = os.getenv("DIGITAL_HUMAN_COMMAND")
    liveportrait_repo: str = os.getenv("LIVEPORTRAIT_REPO", str(Path(__file__).resolve().parents[3] / "engines" / "LivePortrait"))
    liveportrait_python: str = os.getenv("LIVEPORTRAIT_PYTHON", "python")
    liveportrait_detector: str = os.getenv("LIVEPORTRAIT_DETECTOR", "mediapipe").lower()
    liveportrait_detector_model: str | None = os.getenv("LIVEPORTRAIT_DETECTOR_MODEL")
    liveportrait_command: str | None = os.getenv("LIVEPORTRAIT_COMMAND")
    wav2lip_onnx_model: str = os.getenv(
        "WAV2LIP_ONNX_MODEL",
        str(Path(__file__).parent.parent.parent.parent / "storage" / "models" / "wav2lip" / "wav2lip.onnx"),
    )
    wav2lip_onnx_command: str | None = os.getenv("WAV2LIP_ONNX_COMMAND")
    wav2lip_blend_enabled: bool = os.getenv("WAV2LIP_BLEND_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    wav2lip_blend_preset: str = os.getenv("WAV2LIP_BLEND_PRESET", "balanced")
    wav2lip_aperture_atlas_source: str | None = os.getenv("WAV2LIP_APERTURE_ATLAS_SOURCE")
    wav2lip_aperture_atlas_strength: float = float(os.getenv("WAV2LIP_APERTURE_ATLAS_STRENGTH", "0.5"))
    wav2lip_aperture_energy_threshold: float = float(os.getenv("WAV2LIP_APERTURE_ENERGY_THRESHOLD", "0.24"))
    wav2lip_aperture_min_ratio: float = float(os.getenv("WAV2LIP_APERTURE_MIN_RATIO", "0.07"))
    wav2lip_aperture_max_ratio: float = float(os.getenv("WAV2LIP_APERTURE_MAX_RATIO", "0.36"))
    wav2lip_aperture_attack: float = float(os.getenv("WAV2LIP_APERTURE_ATTACK", "1.0"))
    wav2lip_aperture_release: float = float(os.getenv("WAV2LIP_APERTURE_RELEASE", "1.0"))
    wav2lip_quality_diagnostics_enabled: bool = os.getenv("WAV2LIP_QUALITY_DIAGNOSTICS_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    wav2lip_quality_diagnostics_sample_stride: int = int(os.getenv("WAV2LIP_QUALITY_DIAGNOSTICS_SAMPLE_STRIDE", "2"))
    wav2lip_quality_diagnostics_max_frames: int = int(os.getenv("WAV2LIP_QUALITY_DIAGNOSTICS_MAX_FRAMES", "240"))
    heygem_base_url: str = os.getenv("HEYGEM_BASE_URL", "http://127.0.0.1:16008")
    heygem_data_dir: str = os.getenv("HEYGEM_DATA_DIR", str(Path(__file__).resolve().parents[3] / "storage" / "heygem_data" / "face2face" / "temp"))
    heygem_timeout_seconds: int = int(os.getenv("HEYGEM_TIMEOUT_SECONDS", "3600"))
    heygem_ssh_host: str | None = os.getenv("HEYGEM_SSH_HOST")
    heygem_ssh_port: int = int(os.getenv("HEYGEM_SSH_PORT", "22"))
    heygem_ssh_user: str = os.getenv("HEYGEM_SSH_USER", "root")
    heygem_ssh_key_path: str | None = os.getenv("HEYGEM_SSH_KEY_PATH")
    heygem_remote_upload_dir: str = os.getenv(
        "HEYGEM_REMOTE_UPLOAD_DIR",
        "/root/autodl-tmp/oral-video-agent-inputs",
    )
    digital_human_templates_dir: str | None = os.getenv("DIGITAL_HUMAN_TEMPLATES_DIR")
    douyin_cookies_file: str | None = os.getenv("DOUYIN_COOKIES_FILE")


def get_settings() -> Settings:
    return Settings()
