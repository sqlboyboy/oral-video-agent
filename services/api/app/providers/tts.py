from pathlib import Path


class VoiceProvider:
    def synthesize(self, script: str, voice_id: str, output_path: Path) -> Path:
        # MVP placeholder. Replace with CosyVoice, MiniMax, Volcengine, ElevenLabs, etc.
        output_path.write_bytes(b"PLACEHOLDER_AUDIO_WAV")
        return output_path
