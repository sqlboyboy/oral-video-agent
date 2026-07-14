param(
    [string]$ReleaseDirectory = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$cloudEnvPath = Join-Path $repoRoot "services\cloud\.env"
if ([string]::IsNullOrWhiteSpace($ReleaseDirectory)) {
    $ReleaseDirectory = Join-Path $repoRoot "dist\android"
}
$ReleaseDirectory = [IO.Path]::GetFullPath($ReleaseDirectory)
$manifestPath = Join-Path $ReleaseDirectory "latest.json"

if (-not (Test-Path -LiteralPath $cloudEnvPath)) {
    throw "缺少受忽略的 services/cloud/.env，无法读取服务器连接配置。"
}
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "缺少 latest.json，请先构建安卓正式包。"
}

$envValues = @{}
foreach ($line in Get-Content -Encoding UTF8 $cloudEnvPath) {
    if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $envValues[$Matches[1]] = $Matches[2].Trim()
    }
}
$hostName = $envValues['TENCENT_CLOUD_HOST']
$userName = $envValues['TENCENT_CLOUD_USER']
$sshKey = $envValues['TENCENT_CLOUD_SSH_KEY_PATH']
if (-not $hostName -or -not $userName -or -not $sshKey) {
    throw "services/cloud/.env 缺少腾讯云 SSH 配置。"
}

$manifest = Get-Content -Raw -Encoding UTF8 $manifestPath | ConvertFrom-Json
$apkName = [string]$manifest.apk_file
if ([IO.Path]::GetFileName($apkName) -ne $apkName -or -not $apkName.EndsWith('.apk')) {
    throw "latest.json 中的 apk_file 不安全。"
}
$apkPath = Join-Path $ReleaseDirectory $apkName
if (-not (Test-Path -LiteralPath $apkPath)) {
    throw "缺少发布清单指定的 APK：$apkPath"
}
$actualHash = (Get-FileHash -LiteralPath $apkPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne ([string]$manifest.sha256).ToLowerInvariant()) {
    throw "APK SHA-256 与 latest.json 不一致，已停止发布。"
}

$remote = "$userName@$hostName"
$remoteDirectory = "/var/lib/oral-video-agent/cloud/releases/android"
& ssh -i $sshKey $remote "mkdir -p '$remoteDirectory'"
if ($LASTEXITCODE -ne 0) { throw "创建服务器发布目录失败。" }
& scp -i $sshKey $apkPath "${remote}:${remoteDirectory}/${apkName}.tmp"
if ($LASTEXITCODE -ne 0) { throw "上传 APK 失败。" }
& scp -i $sshKey $manifestPath "${remote}:${remoteDirectory}/latest.json.tmp"
if ($LASTEXITCODE -ne 0) { throw "上传发布清单失败。" }
& ssh -i $sshKey $remote `
    "mv '$remoteDirectory/$apkName.tmp' '$remoteDirectory/$apkName' && chmod 0644 '$remoteDirectory/$apkName' && mv '$remoteDirectory/latest.json.tmp' '$remoteDirectory/latest.json' && chmod 0644 '$remoteDirectory/latest.json'"
if ($LASTEXITCODE -ne 0) { throw "服务器原子发布失败。" }

Write-Host "安卓版本已发布到服务器：$apkName"
Write-Host "SHA-256：$actualHash"
