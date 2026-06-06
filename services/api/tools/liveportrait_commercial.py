from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


COMMERCIAL_DETECTORS = {"mediapipe", "yunet", "opencv-yunet", "dlib"}
COMMERCIAL_ENTRYPOINTS = (
    "inference_commercial.py",
    "scripts/inference_commercial.py",
    "tools/inference_commercial.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Commercial LivePortrait adapter. It calls a local LivePortrait fork "
            "that accepts commercial-friendly detector options and a driving "
            "audio file. The stock LivePortrait entrypoint is intentionally not "
            "used by default because it is not an audio-driven lip-sync pipeline."
        )
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--detector", default="mediapipe")
    parser.add_argument("--detector-model")
    return parser.parse_args()


def require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"{label} not found: {path}")
    if not path.is_file():
        raise SystemExit(f"{label} is not a file: {path}")


def find_commercial_entrypoint(repo: Path) -> Path | None:
    for relative in COMMERCIAL_ENTRYPOINTS:
        candidate = repo / relative
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def copy_or_move_output(generated: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if generated.resolve() == output.resolve():
        return
    shutil.copy2(generated, output)


def newest_mp4(path: Path) -> Path | None:
    candidates = [item for item in path.rglob("*.mp4") if item.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def run_commercial_entrypoint(
    *,
    python_executable: str,
    entrypoint: Path,
    repo: Path,
    reference: Path,
    audio: Path,
    output: Path,
    detector: str,
    detector_model: str | None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="liveportrait-commercial-") as temp_dir:
        result_dir = Path(temp_dir) / "result"
        result_dir.mkdir(parents=True, exist_ok=True)
        command = [
            python_executable,
            str(entrypoint),
            "--reference",
            str(reference),
            "--audio",
            str(audio),
            "--output",
            str(output),
            "--result-dir",
            str(result_dir),
            "--detector",
            detector,
        ]
        if detector_model:
            command.extend(["--detector-model", detector_model])

        completed = subprocess.run(
            command,
            cwd=repo,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if completed.returncode != 0:
            tail = "\n".join(completed.stdout.splitlines()[-40:])
            raise SystemExit(
                f"Commercial LivePortrait entrypoint failed with exit code "
                f"{completed.returncode}:\n{tail}"
            )

        if output.exists():
            return
        generated = newest_mp4(result_dir)
        if generated is None:
            raise SystemExit(
                "Commercial LivePortrait entrypoint finished, but no MP4 output was found."
            )
        copy_or_move_output(generated, output)


def main() -> None:
    args = parse_args()
    detector = args.detector.strip().lower()
    if detector not in COMMERCIAL_DETECTORS:
        raise SystemExit(
            f"Unsupported detector '{args.detector}'. Expected one of: "
            f"{', '.join(sorted(COMMERCIAL_DETECTORS))}"
        )
    if detector in {"yunet", "opencv-yunet"} and not args.detector_model:
        raise SystemExit("YuNet mode requires --detector-model.")

    repo = Path(args.repo)
    reference = Path(args.reference)
    audio = Path(args.audio)
    output = Path(args.output)
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"LivePortrait repo not found: {repo}")
    require_file(reference, "Reference video")
    require_file(audio, "Driving audio")

    entrypoint = find_commercial_entrypoint(repo)
    if entrypoint is None:
        stock_entrypoint = repo / "inference.py"
        stock_note = (
            f" A stock LivePortrait entrypoint exists at {stock_entrypoint}, "
            "but it is not used automatically because the stock pipeline is not "
            "audio-driven and may rely on non-product-default face analysis components."
            if stock_entrypoint.exists()
            else ""
        )
        raise SystemExit(
            "No commercial LivePortrait entrypoint was found. Add one of "
            f"{', '.join(COMMERCIAL_ENTRYPOINTS)} to the LivePortrait repo, or set "
            "LIVEPORTRAIT_COMMAND to your own adapter command. The adapter command "
            "must consume --reference/--audio/--output and use your chosen "
            f"{detector} detector path.{stock_note}"
        )

    run_commercial_entrypoint(
        python_executable=sys.executable,
        entrypoint=entrypoint,
        repo=repo,
        reference=reference,
        audio=audio,
        output=output,
        detector=detector,
        detector_model=args.detector_model,
    )


if __name__ == "__main__":
    main()
