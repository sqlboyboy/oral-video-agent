param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$FlutterExe = "<workspace>\flutter\bin\flutter.bat",
    [switch]$SkipFlutterBuild,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$clientDir = Join-Path $RepoRoot "apps\client"
$releaseDir = Join-Path $RepoRoot "apps\client\build\windows\x64\runner\Release"
$apiReleaseDir = Join-Path $RepoRoot "dist\windows-api\oral_video_agent_api"
$payloadDir = Join-Path $RepoRoot "dist\windows-installer\payload"
$zipPath = Join-Path $payloadDir "oral_video_agent_client.zip"
$installerScript = Join-Path $RepoRoot "scripts\install_windows_client.cmd"
$sedPath = Join-Path $RepoRoot "dist\windows-installer\oral_video_agent_setup_ascii.sed"
$installerPath = Join-Path $RepoRoot "dist\windows-installer\OralVideoAgentSetup.exe"
$rootInstallerPath = Join-Path $RepoRoot "dist\OralVideoAgentSetup.exe"

if (-not $SkipFlutterBuild) {
    if (-not (Test-Path -LiteralPath $FlutterExe)) {
        throw "Flutter executable not found: $FlutterExe"
    }
    Push-Location $clientDir
    try {
        & $FlutterExe build windows --release --dart-define=API_BASE=http://127.0.0.1:8000
        if ($LASTEXITCODE -ne 0) {
            throw "Flutter Windows release build failed with exit code: $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath $releaseDir)) {
    throw "Release directory not found: $releaseDir"
}

New-Item -ItemType Directory -Force -Path $payloadDir | Out-Null

function Remove-DirectoryRobust {
    param([Parameter(Mandatory=$true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $emptyDir = Join-Path $env:TEMP ("oral-video-empty-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $emptyDir | Out-Null
    try {
        & robocopy $emptyDir $Path /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -gt 7) {
            throw "Failed to clear directory with robocopy: $Path"
        }
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    finally {
        if (Test-Path -LiteralPath $emptyDir) {
            Remove-Item -LiteralPath $emptyDir -Recurse -Force
        }
    }
}

$runtimeDataNames = @(
    "storage",
    "assets",
    "bgm_uploads",
    "covers",
    "digital_humans",
    "experiments",
    "extracted_audio",
    "logs",
    "outputs",
    "publisher",
    "subtitles",
    "tasks",
    "temp",
    "thumbnails",
    "uploads",
    "voice_refs",
    "cloud_auth.json",
    "accounts.json",
    "jobs.json"
)

foreach ($name in $runtimeDataNames) {
    $target = Join-Path $releaseDir $name
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

foreach ($name in @("clone", "bgm")) {
    $target = Join-Path $releaseDir $name
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

$apiTarget = Join-Path $releaseDir "api"
if (Test-Path -LiteralPath $apiTarget) {
    Remove-DirectoryRobust $apiTarget
}

$cloneSource = Join-Path $RepoRoot "clone"
$bgmSource = Join-Path $RepoRoot "bgm"
if (-not (Test-Path -LiteralPath $cloneSource)) {
    throw "Built-in clone template directory not found: $cloneSource"
}
if (-not (Test-Path -LiteralPath $bgmSource)) {
    throw "Built-in BGM directory not found: $bgmSource"
}
if (-not (Test-Path -LiteralPath (Join-Path $apiReleaseDir "oral_video_agent_api.exe"))) {
    throw "Local API executable not found. Run scripts\build_windows_api_release.ps1 first: $apiReleaseDir"
}

Copy-Item -LiteralPath $cloneSource -Destination (Join-Path $releaseDir "clone") -Recurse -Force
Copy-Item -LiteralPath $bgmSource -Destination (Join-Path $releaseDir "bgm") -Recurse -Force
Copy-Item -LiteralPath $apiReleaseDir -Destination $apiTarget -Recurse -Force

$releaseEnv = @"
ASR_PROVIDER=faster-whisper
WHISPER_MODEL=small
REWRITE_PROVIDER=deepseek
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_TIMEOUT_SECONDS=120
VOICE_PROVIDER=remote-cosyvoice
VOICE_BASE_URL=http://127.0.0.1:16010
VOICE_TIMEOUT_SECONDS=1800
DIGITAL_HUMAN_PROVIDER=heygem-local
HEYGEM_BASE_URL=http://127.0.0.1:16008
HEYGEM_TIMEOUT_SECONDS=3600
WAV2LIP_BLEND_ENABLED=true
"@
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $apiTarget ".env"), $releaseEnv, $utf8NoBom)
[System.IO.File]::WriteAllText((Join-Path $releaseDir ".env"), $releaseEnv, $utf8NoBom)

$playwrightCache = Join-Path $env:LOCALAPPDATA "ms-playwright"
$headlessShell = $null
if (Test-Path -LiteralPath $playwrightCache) {
    $headlessShell = Get-ChildItem -LiteralPath $playwrightCache -Directory -Filter "chromium_headless_shell-*" |
        Sort-Object LastWriteTime |
        Select-Object -Last 1
}
if ($null -eq $headlessShell) {
    Push-Location (Join-Path $RepoRoot "services\api")
    try {
        uv run playwright install chromium
    }
    finally {
        Pop-Location
    }
    if (Test-Path -LiteralPath $playwrightCache) {
        $headlessShell = Get-ChildItem -LiteralPath $playwrightCache -Directory -Filter "chromium_headless_shell-*" |
            Sort-Object LastWriteTime |
            Select-Object -Last 1
    }
}
if ($null -eq $headlessShell) {
    throw "Playwright Chromium headless shell was not found. Run: cd services\api && uv run playwright install chromium"
}

$playwrightLocalBrowsers = Join-Path $apiTarget "_internal\playwright\driver\package\.local-browsers"
New-Item -ItemType Directory -Force -Path $playwrightLocalBrowsers | Out-Null
$browserTarget = Join-Path $playwrightLocalBrowsers $headlessShell.Name
if (Test-Path -LiteralPath $browserTarget) {
    Remove-DirectoryRobust $browserTarget
}
$robocopyArgs = @(
    $headlessShell.FullName,
    $browserTarget,
    "/E",
    "/NFL",
    "/NDL",
    "/NJH",
    "/NJS",
    "/NP"
)
& robocopy @robocopyArgs | Out-Null
if ($LASTEXITCODE -gt 7) {
    throw "Failed to copy Playwright Chromium with robocopy. Exit code: $LASTEXITCODE"
}

Copy-Item -LiteralPath $installerScript -Destination (Join-Path $payloadDir "install.cmd") -Force

Add-Type -AssemblyName System.IO.Compression.FileSystem
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

& tar.exe -a -cf $zipPath -C $releaseDir .
if ($LASTEXITCODE -ne 0) {
    throw "Release zip creation failed with tar.exe. Exit code: $LASTEXITCODE"
}

$zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $entries = @($zip.Entries | ForEach-Object {
        $name = $_.FullName.Replace("\", "/")
        if ($name.StartsWith("./", [System.StringComparison]::Ordinal)) {
            $name = $name.Substring(2)
        }
        $name
    })
    $forbiddenPrefixes = @(
        "storage/",
        "assets/",
        "bgm_uploads/",
        "covers/",
        "digital_humans/",
        "experiments/",
        "extracted_audio/",
        "logs/",
        "outputs/",
        "publisher/",
        "subtitles/",
        "tasks/",
        "temp/",
        "thumbnails/",
        "uploads/",
        "voice_refs/"
    )
    foreach ($prefix in $forbiddenPrefixes) {
        if ($entries | Where-Object { $_.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) }) {
            throw "Release zip contains runtime user data: $prefix"
        }
    }
    foreach ($fileName in @("cloud_auth.json", "accounts.json", "jobs.json")) {
        if ($entries | Where-Object { [System.IO.Path]::GetFileName($_) -ieq $fileName }) {
            throw "Release zip contains user state file: $fileName"
        }
    }
    if (-not ($entries | Where-Object { $_.StartsWith("clone/", [System.StringComparison]::OrdinalIgnoreCase) })) {
        throw "Release zip is missing built-in clone templates."
    }
    if (-not ($entries | Where-Object { $_.StartsWith("bgm/", [System.StringComparison]::OrdinalIgnoreCase) })) {
        throw "Release zip is missing built-in BGM templates."
    }
    if (-not ($entries | Where-Object { $_ -ieq "api/oral_video_agent_api.exe" })) {
        throw "Release zip is missing local API executable."
    }
    if (-not ($entries | Where-Object { $_ -ieq "api/.env" })) {
        throw "Release zip is missing local API release environment."
    }
    if (-not ($entries | Where-Object { $_.StartsWith("api/_internal/playwright/driver/package/.local-browsers/chromium_headless_shell-", [System.StringComparison]::OrdinalIgnoreCase) })) {
        throw "Release zip is missing Playwright bundled Chromium."
    }
}
finally {
    $zip.Dispose()
}

Write-Host "Clean client payload created: $zipPath"

if ($SkipInstaller) {
    Write-Host "Skipped IExpress installer build."
}
elseif (Test-Path -LiteralPath $sedPath) {
    $installerBackupPath = "$installerPath.bak"
    if (Test-Path -LiteralPath $installerBackupPath) {
        Remove-Item -LiteralPath $installerBackupPath -Force
    }
    if (Test-Path -LiteralPath $installerPath) {
        Copy-Item -LiteralPath $installerPath -Destination $installerBackupPath -Force
        Remove-Item -LiteralPath $installerPath -Force
    }
    $sedDir = Split-Path -Parent $sedPath
    $sedName = Split-Path -Leaf $sedPath
    $iexpressPath = Join-Path $env:SystemRoot "System32\iexpress.exe"
    $iexpressCommand = 'cd /d "{0}" && {1} /N /Q {2}' -f $sedDir, $iexpressPath, $sedName
    & cmd.exe /c $iexpressCommand
    $iexpressExitCode = $LASTEXITCODE
    if ($iexpressExitCode -ne 0 -and $null -ne $iexpressExitCode) {
        throw "IExpress installer build failed with exit code $iexpressExitCode"
    }
    if (-not (Test-Path -LiteralPath $installerPath)) {
        if (Test-Path -LiteralPath $installerBackupPath) {
            Copy-Item -LiteralPath $installerBackupPath -Destination $installerPath -Force
        }
        throw "IExpress did not create installer: $installerPath"
    }
    if (Test-Path -LiteralPath $installerBackupPath) {
        Remove-Item -LiteralPath $installerBackupPath -Force
    }
    Copy-Item -LiteralPath $installerPath -Destination $rootInstallerPath -Force
    Write-Host "Installer created: $installerPath"
    Write-Host "Installer copied: $rootInstallerPath"
}
else {
    Write-Host "Installer SED file not found, skipped installer build: $sedPath"
}
