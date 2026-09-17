@echo off
setlocal
if not defined CLOUD_API_BASE (
  echo Set CLOUD_API_BASE to your own cloud API URL before building.
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_windows_api_release.ps1"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\package_windows_client_release.ps1" -CloudApiBase "%CLOUD_API_BASE%"
exit /b %errorlevel%
