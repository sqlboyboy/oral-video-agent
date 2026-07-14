param(
    [string]$CloudApiBase = "https://api.example.com",
    [string]$OutputDirectory = "",
    [int]$MinSupportedVersionCode = 3,
    [switch]$ForceUpdate,
    [string[]]$ReleaseNotes = @(
        "修复部分安卓手机无法选择 M4A 声音样本的问题",
        "视频页只显示数字人原视频，成品生成后自动替换",
        "保留 HTTPS 安全更新、正式签名和完整性校验"
    )
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$clientRoot = Join-Path $repoRoot "apps\client"
$flutter = "<workspace>\flutter\bin\flutter.bat"
$pubspecPath = Join-Path $clientRoot "pubspec.yaml"
$keyPropertiesPath = Join-Path $clientRoot "android\key.properties"

if (-not $CloudApiBase.StartsWith("https://", [StringComparison]::OrdinalIgnoreCase)) {
    throw "正式安卓包只允许使用 HTTPS 云端地址。"
}
if (-not (Test-Path -LiteralPath $keyPropertiesPath)) {
    throw "缺少正式签名配置。请先运行 scripts\configure_android_release_signing.ps1。"
}
if (-not (Test-Path -LiteralPath $flutter)) {
    throw "未找到 Flutter：$flutter"
}

$pubspec = Get-Content -Raw -Encoding UTF8 $pubspecPath
$versionMatch = [Regex]::Match($pubspec, '(?m)^version:\s*([0-9][^+\s]*)\+([0-9]+)\s*$')
if (-not $versionMatch.Success) {
    throw "无法从 pubspec.yaml 读取 versionName 和 versionCode。"
}
$versionName = $versionMatch.Groups[1].Value
$versionCode = [int]$versionMatch.Groups[2].Value
if ($MinSupportedVersionCode -gt $versionCode) {
    throw "MinSupportedVersionCode 不能大于当前 versionCode。"
}

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot "dist\android"
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$symbolsDirectory = Join-Path $OutputDirectory "symbols-$versionName-$versionCode"
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $symbolsDirectory | Out-Null

Push-Location $clientRoot
try {
    & $flutter pub get
    if ($LASTEXITCODE -ne 0) { throw "flutter pub get 失败。" }
    & $flutter analyze lib\main.dart lib\mobile.dart lib\mobile_updater.dart
    if ($LASTEXITCODE -ne 0) { throw "Flutter 静态检查失败。" }
    & $flutter build apk `
        --release `
        --obfuscate `
        "--split-debug-info=$symbolsDirectory" `
        "--dart-define=CLOUD_API_BASE=$CloudApiBase"
    if ($LASTEXITCODE -ne 0) { throw "Flutter APK 构建失败。" }
} finally {
    Pop-Location
}

$sourceApk = Join-Path $clientRoot "build\app\outputs\flutter-apk\app-release.apk"
if (-not (Test-Path -LiteralPath $sourceApk)) {
    throw "构建成功但未找到 APK：$sourceApk"
}
$apkName = "jiesu-oral-video-$versionName-$versionCode.apk"
$targetApk = Join-Path $OutputDirectory $apkName
Copy-Item -LiteralPath $sourceApk -Destination $targetApk -Force
$apkItem = Get-Item -LiteralPath $targetApk
$sha256 = (Get-FileHash -LiteralPath $targetApk -Algorithm SHA256).Hash.ToLowerInvariant()

$manifest = [ordered]@{
    version_name = $versionName
    version_code = $versionCode
    apk_file = $apkName
    sha256 = $sha256
    size_bytes = $apkItem.Length
    min_supported_version_code = $MinSupportedVersionCode
    force_update = [bool]$ForceUpdate
    release_notes = @($ReleaseNotes)
    published_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
}
$manifestJson = $manifest | ConvertTo-Json -Depth 5
$manifestPath = Join-Path $OutputDirectory "latest.json"
[IO.File]::WriteAllText(
    $manifestPath,
    $manifestJson + "`n",
    [Text.UTF8Encoding]::new($false)
)

Write-Host "安卓正式包构建完成：$targetApk"
Write-Host "版本：$versionName ($versionCode)"
Write-Host "SHA-256：$sha256"
Write-Host "发布清单：$manifestPath"
Write-Host "混淆符号：$symbolsDirectory（请安全保留，不要发布）"
