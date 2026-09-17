import os
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_test_outputs_stay_inside_repository(tmp_path):
    assert Path(tmp_path).resolve().is_relative_to(REPO_ROOT)
    assert Path(tempfile.gettempdir()).resolve().is_relative_to(REPO_ROOT)
    for name in (
        "TMP", "TEMP", "TMPDIR", "UV_CACHE_DIR", "HF_HOME",
        "TRANSFORMERS_CACHE", "XDG_CACHE_HOME",
    ):
        assert Path(os.environ[name]).resolve().is_relative_to(REPO_ROOT)
