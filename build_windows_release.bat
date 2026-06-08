@echo off
set TMP=<repo>\storage\temp\flutter
set TEMP=<repo>\storage\temp\flutter
set TMPDIR=<repo>\storage\temp\flutter
set PUB_CACHE=<repo>\apps\client\.pub-cache
if not exist <repo>\storage\temp\flutter mkdir <repo>\storage\temp\flutter
if not exist <repo>\apps\client\.pub-cache mkdir <repo>\apps\client\.pub-cache
echo ============================================
echo Flutter Windows Build
echo ============================================
cd /d d:\AI\AI_Project\oral-video-agent\apps\client
echo.
echo Step 1: flutter pub get
<workspace>\flutter\bin\flutter.bat pub get
if %errorlevel% neq 0 (
    echo ERROR: flutter pub get failed
    pause
    exit /b %errorlevel%
)
echo.
echo Step 2: flutter build windows
<workspace>\flutter\bin\flutter.bat build windows --release
if %errorlevel% neq 0 (
    echo ERROR: flutter build windows failed
    pause
    exit /b %errorlevel%
)
echo.
echo ============================================
echo BUILD SUCCESS!
echo Exe location: build\windows\x64\runner\Release\oral_video.exe
echo ============================================
pause

