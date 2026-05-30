from pathlib import Path
from typing import Optional


class AsrProvider:
    def transcribe(self, audio_path: Optional[Path], source_hint: str = "") -> str:
        # MVP placeholder. Replace with faster-whisper, Whisper API, or a cloud ASR provider.
        if source_hint:
            return f"这是从视频中识别出的口播内容示例。来源：{source_hint}。"
        return "这是从视频中识别出的口播内容示例：开头抓住用户注意力，中间讲清楚痛点和解决方案，结尾引导行动。"
