import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from ..models import RenderOptions


class Renderer:
    def build_ffmpeg_command(
        self,
        source_video: Optional[Path],
        voice_audio: Path,
        subtitle_file: Path,
        options: RenderOptions,
        output_path: Path,
        bgm_audio: Optional[Path] = None,
    ) -> List[str]:
        if source_video is None:
            raise ValueError("source_video is required for real FFmpeg rendering")

        command = ["ffmpeg", "-y", "-i", str(source_video), "-i", str(voice_audio)]
        filter_parts = []
        audio_inputs = "[1:a]"

        if bgm_audio is not None:
            command.extend(["-i", str(bgm_audio)])
            filter_parts.append(f"[2:a]volume={options.bgm_volume},aloop=loop=-1:size=2e+09[bgm]")
            filter_parts.append("[1:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]")
            audio_inputs = "[aout]"

        subtitle_path = str(subtitle_file).replace("\\", "/").replace(":", "\\:")
        filter_parts.append(f"[0:v]subtitles='{subtitle_path}'[vout]")

        command.extend([
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vout]",
            "-map",
            audio_inputs,
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ])
        return command

    def render(
        self,
        task_id: str,
        script: str,
        options: RenderOptions,
        output_path: Path,
        source_video: Optional[Path] = None,
        voice_audio: Optional[Path] = None,
        subtitle_file: Optional[Path] = None,
        bgm_audio: Optional[Path] = None,
    ) -> Path:
        if source_video and voice_audio and subtitle_file and shutil.which("ffmpeg"):
            command = self.build_ffmpeg_command(source_video, voice_audio, subtitle_file, options, output_path, bgm_audio)
            subprocess.run(command, check=True)
            return output_path

        output_path.write_text(
            "This placeholder represents the rendered MP4.\n"
            "Real FFmpeg rendering is skipped until source video, generated voice audio, subtitles, and ffmpeg are available.\n"
            f"task_id={task_id}\n"
            f"voice_id={options.voice_id}\n"
            f"bgm_id={options.bgm_id}\n"
            f"bgm_volume={options.bgm_volume}\n"
            f"script={script}\n",
            encoding="utf-8",
        )
        return output_path
