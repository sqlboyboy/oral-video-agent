$ErrorActionPreference = "Stop"

$hostName = "gpu.example.com"
$sshPort = 22
$heygemLocalPort = 16008
$heygemRemotePort = 6008
$voiceLocalPort = 16010
$voiceRemotePort = 6010
$keyPath = Join-Path $env:USERPROFILE ".ssh\oral_video_autodl"

if (-not (Test-Path -LiteralPath $keyPath)) {
    throw "SSH key not found: $keyPath"
}

$sshPath = (Get-Command ssh.exe -ErrorAction Stop).Source
$pattern = "*${heygemLocalPort}:127.0.0.1:${heygemRemotePort}*${voiceLocalPort}:127.0.0.1:${voiceRemotePort}*"
$existing = Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "ssh.exe" -and $_.CommandLine -like $pattern }

if (-not $existing) {
    Start-Process `
        -FilePath $sshPath `
        -ArgumentList @(
            "-N",
            "-L", "${heygemLocalPort}:127.0.0.1:${heygemRemotePort}",
            "-L", "${voiceLocalPort}:127.0.0.1:${voiceRemotePort}",
            "-p", "$sshPort",
            "-i", $keyPath,
            "-o", "BatchMode=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "root@$hostName"
        ) `
        -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

$heygemHealth = Invoke-RestMethod "http://127.0.0.1:$heygemLocalPort/api/health" -TimeoutSec 10
if ($heygemHealth.gpu_available -ne $true) {
    throw "HeyGem API is reachable, but GPU is unavailable."
}

$voiceHealth = Invoke-RestMethod "http://127.0.0.1:$voiceLocalPort/api/health" -TimeoutSec 30
if ($voiceHealth.gpu_available -ne $true) {
    throw "CosyVoice API is reachable, but GPU is unavailable."
}

@{
    heygem = $heygemHealth
    voice = $voiceHealth
} | ConvertTo-Json -Depth 4
