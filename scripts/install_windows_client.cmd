@echo off
setlocal

set "INSTALL_DIR=%LOCALAPPDATA%\Programs\OralVideoAgent"
set "ZIP_PATH=%~dp0oral_video_agent_client.zip"

taskkill /IM oral_video_agent_client.exe /F >nul 2>nul

if not exist "%ZIP_PATH%" (
  echo Missing payload: "%ZIP_PATH%"
  exit /b 1
)

for %%D in (
  "%APPDATA%\oral_video_agent_client"
  "%APPDATA%\oral-video-agent"
  "%APPDATA%\OralVideoAgent"
  "%APPDATA%\JiesuKoubo"
  "%LOCALAPPDATA%\oral_video_agent_client"
  "%LOCALAPPDATA%\oral-video-agent"
  "%LOCALAPPDATA%\OralVideoAgent"
  "%LOCALAPPDATA%\JiesuKoubo"
) do (
  if exist "%%~D" rmdir /s /q "%%~D"
)

if exist "%INSTALL_DIR%" (
  rmdir /s /q "%INSTALL_DIR%"
)
mkdir "%INSTALL_DIR%" >nul 2>nul

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP_PATH%' -DestinationPath '%INSTALL_DIR%' -Force"
if errorlevel 1 exit /b %errorlevel%

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $shortcut = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Oral Video Agent.lnk'); $shortcut.TargetPath = '%INSTALL_DIR%\oral_video_agent_client.exe'; $shortcut.WorkingDirectory = '%INSTALL_DIR%'; $shortcut.Save()"

start "" "%INSTALL_DIR%\oral_video_agent_client.exe"
exit /b 0
