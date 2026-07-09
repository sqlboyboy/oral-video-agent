import argparse
import os
import sys
from pathlib import Path

import uvicorn


def _app_home() -> Path:
    configured = os.getenv("ORAL_VIDEO_AGENT_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def main() -> None:
    parser = argparse.ArgumentParser(description="Oral Video Agent local API")
    parser.add_argument("--host", default=os.getenv("ORAL_VIDEO_AGENT_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("ORAL_VIDEO_AGENT_PORT", "8000")),
    )
    parser.add_argument("--log-level", default=os.getenv("ORAL_VIDEO_AGENT_LOG_LEVEL", "info"))
    args = parser.parse_args()

    app_home = _app_home()
    os.environ.setdefault("ORAL_VIDEO_AGENT_HOME", str(app_home))
    if getattr(sys, "frozen", False):
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    (app_home / "storage" / "logs").mkdir(parents=True, exist_ok=True)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        access_log=True,
    )


if __name__ == "__main__":
    main()
