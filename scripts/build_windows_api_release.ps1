param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

$apiDir = Join-Path $RepoRoot "services\api"
$distDir = Join-Path $RepoRoot "dist\windows-api"
$workDir = Join-Path $RepoRoot "storage\temp\pyinstaller-api"
$specDir = Join-Path $RepoRoot "storage\temp\pyinstaller-spec"

if (-not (Test-Path -LiteralPath $apiDir)) {
    throw "API directory not found: $apiDir"
}

New-Item -ItemType Directory -Force -Path $distDir, $workDir, $specDir | Out-Null

$env:PATH = (($env:PATH -split ";") |
    Where-Object { $_ -and ($_ -notlike "*\VanDyke Software\Clients\*") }) -join ";"

Push-Location $apiDir
try {
    uv run --with pyinstaller pyinstaller `
        --noconfirm `
        --clean `
        --name oral_video_agent_api `
        --distpath $distDir `
        --workpath $workDir `
        --specpath $specDir `
        --hidden-import app.main `
        --hidden-import app.desktop_server `
        --collect-submodules app `
        --exclude-module torch `
        --exclude-module torchaudio `
        --exclude-module torchvision `
        --exclude-module torchgen `
        --exclude-module torch._inductor `
        --exclude-module torch.distributed `
        --exclude-module torch.testing `
        app\desktop_server.py
}
finally {
    Pop-Location
}

$exePath = Join-Path $distDir "oral_video_agent_api\oral_video_agent_api.exe"
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "API executable was not created: $exePath"
}

$internalDir = Join-Path $distDir "oral_video_agent_api\_internal"
$systemDir = Join-Path $env:WINDIR "System32"
$vcRuntimePatterns = @(
    "msvcp140*.dll",
    "vcruntime140*.dll",
    "concrt140.dll",
    "vcomp140.dll"
)
foreach ($pattern in $vcRuntimePatterns) {
    Get-ChildItem -LiteralPath $systemDir -Filter $pattern -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -notmatch "d\.dll$" -and
            $_.Name -notmatch "140d[_\.]" -and
            $_.Name -notmatch "_clr0400\.dll$" -and
            $_.Name -notmatch "clr0400\.dll$"
        } |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $internalDir $_.Name) -Force
        }
}

function Assert-MinimumDllVersion {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$MinimumVersion
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required runtime DLL was not bundled: $Path"
    }
    $versionText = (Get-Item -LiteralPath $Path).VersionInfo.FileVersion
    $version = [version](($versionText -split " ")[0])
    if ($version -lt [version]$MinimumVersion) {
        throw "Runtime DLL is too old: $Path ($versionText), expected >= $MinimumVersion"
    }
}

Assert-MinimumDllVersion -Path (Join-Path $internalDir "msvcp140.dll") -MinimumVersion "14.40.0.0"
Assert-MinimumDllVersion -Path (Join-Path $internalDir "vcruntime140.dll") -MinimumVersion "14.40.0.0"

Write-Host "API executable created: $exePath"
