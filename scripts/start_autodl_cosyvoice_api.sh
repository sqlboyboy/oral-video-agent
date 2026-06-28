#!/usr/bin/env bash
set -euo pipefail

BASE=/root/autodl-tmp/cosyvoice
export COSYVOICE_REPO="$BASE/CosyVoice"
export COSYVOICE_MODEL="$BASE/models/CosyVoice-300M-25Hz"
export LD_PRELOAD="/usr/lib/x86_64-linux-gnu/libcuda.so.580.76.05${LD_PRELOAD:+:$LD_PRELOAD}"

cd "$BASE"
exec "$BASE/env/bin/uvicorn" voice_api:app --host 127.0.0.1 --port 6010
