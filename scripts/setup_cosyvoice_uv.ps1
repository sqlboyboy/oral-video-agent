$ErrorActionPreference = "Stop"

$repo = "<workspace>\engines\CosyVoice"
$model = "<workspace>\models\CosyVoice-300M-25Hz"

New-Item -ItemType Directory -Force -Path "<workspace>\engines", "<workspace>\models" | Out-Null

if (-not (Test-Path -LiteralPath $repo)) {
    git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git $repo
} else {
    git -C $repo submodule update --init --recursive
}

uv python install 3.10
if (-not (Test-Path -LiteralPath (Join-Path $repo ".venv"))) {
    uv venv (Join-Path $repo ".venv") --python 3.10
}

$python = Join-Path $repo ".venv\Scripts\python.exe"
uv pip install --python $python "setuptools<81" wheel packaging
uv pip install --python $python openai-whisper==20231117 --no-build-isolation
uv pip install --python $python -r (Join-Path $repo "requirements.txt")
uv pip install --python $python av

@'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
'@ | uv run --python $python -

Write-Host "CosyVoice repo: $repo"
Write-Host "CosyVoice model target: $model"
Write-Host "Download model with: uv run --no-project --python $python -c `"from modelscope import snapshot_download; snapshot_download('iic/CosyVoice-300M-25Hz', local_dir=r'$model')`""
