from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="High quality mouth-sync adapter.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--use-float16", action="store_true")
    return parser.parse_args()


def require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"{label} not found: {path}")
    if not path.is_file():
        raise SystemExit(f"{label} is not a file: {path}")


def require_dir(path: Path, label: str) -> None:
    if not path.exists() or not path.is_dir():
        raise SystemExit(f"{label} not found: {path}")


def newest_mp4(path: Path) -> Path | None:
    candidates = [item for item in path.rglob("*.mp4") if item.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def default_temp_root() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    path = Path(os.getenv("MUSETALK_TEMP_DIR", project_root / "storage" / "temp" / "musetalk"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def main() -> None:
    args = parse_args()
    repo = Path(args.repo)
    reference = Path(args.reference)
    audio = Path(args.audio)
    output = Path(args.output)

    require_dir(repo, "MuseTalk repo")
    require_file(reference, "Reference video")
    require_file(audio, "Driving audio")

    inference = repo / "scripts" / "inference.py"
    require_file(inference, "MuseTalk inference script")

    models = repo / "models"
    require_file(models / "musetalkV15" / "unet.pth", "MuseTalk v1.5 model")
    require_file(models / "musetalkV15" / "musetalk.json", "MuseTalk v1.5 config")
    require_dir(models / "sd-vae", "MuseTalk VAE")
    require_dir(models / "whisper", "MuseTalk Whisper")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="musetalk-hq-", dir=str(default_temp_root())) as temp_dir:
        temp = Path(temp_dir)
        config = temp / "inference.yaml"
        result_dir = temp / "results"
        result_name = output.name
        config.write_text(
            "\n".join(
                [
                    "task_0:",
                    f' video_path: "{reference.as_posix()}"',
                    f' audio_path: "{audio.as_posix()}"',
                    f' result_name: "{result_name}"',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        command = [
            sys.executable,
            "-m",
            "scripts.inference",
            "--inference_config",
            str(config),
            "--result_dir",
            str(result_dir),
            "--unet_model_path",
            str(models / "musetalkV15" / "unet.pth"),
            "--unet_config",
            str(models / "musetalkV15" / "musetalk.json"),
            "--whisper_dir",
            str(models / "whisper"),
            "--version",
            "v15",
            "--batch_size",
            str(args.batch_size),
            "--output_vid_name",
            result_name,
            "--ffmpeg_path",
            str(Path(get_ffmpeg_exe())),
        ]
        if args.use_float16:
            command.append("--use_float16")

        env = os.environ.copy()
        ffmpeg_dir = str(Path(get_ffmpeg_exe()).parent)
        env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")
        completed = subprocess.run(
            command,
            cwd=repo,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if completed.returncode != 0:
            tail = "\n".join(completed.stdout.splitlines()[-60:])
            raise SystemExit(f"高清模式口型生成失败，退出码 {completed.returncode}:\n{tail}")

        generated = result_dir / "v15" / result_name
        if not generated.exists():
            generated = newest_mp4(result_dir)
        if generated is None:
            tail = "\n".join(completed.stdout.splitlines()[-60:])
            raise SystemExit(f"高清模式未找到输出视频:\n{tail}")
        shutil.copy2(generated, output)


if __name__ == "__main__":
    main()
