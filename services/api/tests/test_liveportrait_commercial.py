import pytest

from tools.liveportrait_commercial import main


def test_liveportrait_adapter_requires_commercial_entrypoint(tmp_path, monkeypatch):
    repo = tmp_path / "LivePortrait"
    repo.mkdir()
    (repo / "inference.py").write_text("# stock entrypoint\n", encoding="utf-8")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"video")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "output.mp4"

    monkeypatch.setattr(
        "sys.argv",
        [
            "liveportrait_commercial.py",
            "--repo",
            str(repo),
            "--reference",
            str(reference),
            "--audio",
            str(audio),
            "--output",
            str(output),
            "--detector",
            "mediapipe",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert "No commercial LivePortrait entrypoint was found" in str(exc.value)
    assert "stock LivePortrait entrypoint exists" in str(exc.value)


def test_liveportrait_adapter_calls_commercial_entrypoint(tmp_path, monkeypatch):
    repo = tmp_path / "LivePortrait"
    repo.mkdir()
    entrypoint = repo / "inference_commercial.py"
    entrypoint.write_text(
        """
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--reference")
parser.add_argument("--audio")
parser.add_argument("--output")
parser.add_argument("--result-dir")
parser.add_argument("--detector")
args = parser.parse_args()
Path(args.output).write_bytes(b"fake-mp4")
""".strip(),
        encoding="utf-8",
    )
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"video")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "output.mp4"

    monkeypatch.setattr(
        "sys.argv",
        [
            "liveportrait_commercial.py",
            "--repo",
            str(repo),
            "--reference",
            str(reference),
            "--audio",
            str(audio),
            "--output",
            str(output),
            "--detector",
            "mediapipe",
        ],
    )

    main()

    assert output.read_bytes() == b"fake-mp4"
