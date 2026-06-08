import os
import tempfile
from pathlib import Path


def test_test_outputs_stay_on_d_drive(tmp_path):
    assert Path(tmp_path).drive.upper() == "D:"
    assert Path(tempfile.gettempdir()).drive.upper() == "D:"

    for name in (
        "TMP",
        "TEMP",
        "TMPDIR",
        "UV_CACHE_DIR",
        "HF_HOME",
        "TRANSFORMERS_CACHE",
        "XDG_CACHE_HOME",
    ):
        assert Path(os.environ[name]).drive.upper() == "D:"
