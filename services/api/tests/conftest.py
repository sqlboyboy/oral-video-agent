import os
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_TEMP_ROOT = REPO_ROOT / "storage" / "temp" / "pytest"
CACHE_ROOT = REPO_ROOT / "storage" / "temp" / "cache"


def _force_env(name: str, value: Path | str) -> None:
    os.environ[name] = str(value)


TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
CACHE_ROOT.mkdir(parents=True, exist_ok=True)

_force_env("TMP", TEST_TEMP_ROOT)
_force_env("TEMP", TEST_TEMP_ROOT)
_force_env("TMPDIR", TEST_TEMP_ROOT)
tempfile.tempdir = str(TEST_TEMP_ROOT)

_force_env("UV_CACHE_DIR", REPO_ROOT / ".uv-cache")
_force_env("HF_HOME", CACHE_ROOT / "huggingface")
_force_env("TRANSFORMERS_CACHE", CACHE_ROOT / "huggingface" / "transformers")
_force_env("XDG_CACHE_HOME", CACHE_ROOT / "xdg")
_force_env("TORCH_HOME", CACHE_ROOT / "torch")
_force_env("PIP_CACHE_DIR", CACHE_ROOT / "pip")
_force_env("PLAYWRIGHT_BROWSERS_PATH", CACHE_ROOT / "ms-playwright")
_force_env("NUMBA_CACHE_DIR", CACHE_ROOT / "numba")
_force_env("MPLCONFIGDIR", CACHE_ROOT / "matplotlib")

_force_env("ASR_PROVIDER", "placeholder")
_force_env("REWRITE_PROVIDER", "placeholder")
_force_env("VOICE_PROVIDER", "placeholder")
_force_env("DIGITAL_HUMAN_PROVIDER", "placeholder")


def pytest_configure(config):
    if not config.option.basetemp:
        config.option.basetemp = str(TEST_TEMP_ROOT / "basetemp")
