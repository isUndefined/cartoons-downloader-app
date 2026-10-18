@echo off
setlocal
cd /d "%~dp0"
title Cartoon Downloader Desktop v0.29

echo ============================================================
echo   Cartoon Downloader Desktop v0.29
echo   Fully bundled runtime - no setup downloads
echo ============================================================
echo.

set "LOCAL_PY=%CD%\runtime\python\python.exe"
set "YTDLP=%CD%\tools\yt-dlp\yt-dlp.exe"
set "DENO=%CD%\tools\deno\deno.exe"
set "FFMPEG=%CD%\tools\ffmpeg\ffmpeg.exe"
set "FFPROBE=%CD%\tools\ffmpeg\ffprobe.exe"

if not exist "%LOCAL_PY%" goto :missing
if not exist "%YTDLP%" goto :missing
if not exist "%DENO%" goto :missing
if not exist "%FFMPEG%" goto :missing
if not exist "%FFPROBE%" goto :missing

echo [OK] Bundled Python
echo [OK] Bundled yt-dlp
echo [OK] Bundled Deno
echo [OK] Bundled FFmpeg / ffprobe
echo [RUN] Starting Cartoon Downloader...
"%LOCAL_PY%" -E -s -B app.py
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo Application stopped with exit code %RC%.
  pause
)
exit /b %RC%

:missing
echo ERROR: The portable package is incomplete.
echo Expected local files:
echo   runtime\python\python.exe
echo   tools\yt-dlp\yt-dlp.exe
echo   tools\deno\deno.exe
echo   tools\ffmpeg\ffmpeg.exe
echo   tools\ffmpeg\ffprobe.exe
echo.
echo Re-extract the complete package. Nothing needs to be downloaded or installed.
pause
exit /b 1
