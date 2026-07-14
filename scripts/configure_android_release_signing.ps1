param(
    [string]$KeystorePath = "$env:USERPROFILE\.oral-video-agent\android-release.jks",
    [string]$KeyAlias = "jiesu_android_release"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$keyPropertiesPath = Join-Path $repoRoot "apps\client\android\key.properties"
$keytool = (Get-Command keytool.exe -ErrorAction Stop).Source

function Protect-PrivateFile([string]$Path) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $icacls = (Get-Command icacls.exe -ErrorAction Stop).Source
    & $icacls $Path /inheritance:r /grant:r "$identity`:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "无法收紧签名文件访问权限：$Path"
    }
}

if ((Test-Path -LiteralPath $KeystorePath) -or (Test-Path -LiteralPath $keyPropertiesPath)) {
    if ((Test-Path -LiteralPath $KeystorePath) -and (Test-Path -LiteralPath $keyPropertiesPath)) {
        Protect-PrivateFile $KeystorePath
        Protect-PrivateFile $keyPropertiesPath
        Write-Host "正式签名已经配置，未生成或覆盖任何密钥。"
        Write-Host "密钥文件：$KeystorePath"
        Write-Host "配置文件：$keyPropertiesPath"
        exit 0
    }
    throw "检测到不完整的签名配置。请先人工核对现有密钥和 key.properties，脚本不会自动覆盖。"
}

$keystoreDirectory = Split-Path -Parent $KeystorePath
New-Item -ItemType Directory -Force -Path $keystoreDirectory | Out-Null

$randomBytes = New-Object byte[] 36
$randomNumberGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $randomNumberGenerator.GetBytes($randomBytes)
} finally {
    $randomNumberGenerator.Dispose()
}
$password = [Convert]::ToBase64String($randomBytes).Replace("+", "-").Replace("/", "_").TrimEnd("=")

& $keytool -genkeypair `
    -keystore $KeystorePath `
    -storetype PKCS12 `
    -storepass $password `
    -keypass $password `
    -alias $KeyAlias `
    -keyalg RSA `
    -keysize 4096 `
    -sigalg SHA256withRSA `
    -validity 10000 `
    -dname "CN=Jiesu Oral Video Agent, O=Jiesu, C=CN"
if ($LASTEXITCODE -ne 0) {
    throw "keytool 生成正式签名失败，退出码：$LASTEXITCODE"
}

$normalizedKeystorePath = $KeystorePath.Replace("\", "/")
$properties = @(
    "storePassword=$password"
    "keyPassword=$password"
    "keyAlias=$KeyAlias"
    "storeFile=$normalizedKeystorePath"
) -join "`n"
[IO.File]::WriteAllText(
    $keyPropertiesPath,
    $properties + "`n",
    [Text.UTF8Encoding]::new($false)
)
Protect-PrivateFile $KeystorePath
Protect-PrivateFile $keyPropertiesPath

Write-Host "正式签名配置完成。密码没有输出到终端。"
Write-Host "密钥文件：$KeystorePath"
Write-Host "配置文件：$keyPropertiesPath（已被 Git 忽略）"
Write-Warning "请把密钥文件和 key.properties 做两份离线加密备份。丢失密钥后将无法覆盖更新已安装的正式版。"
