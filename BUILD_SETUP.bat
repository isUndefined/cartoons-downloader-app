@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 exit /b 1
set "BUILD_PYTHON=%~dp0runtime\python\python.exe"
if not exist "%BUILD_PYTHON%" goto :missing
"%BUILD_PYTHON%" -E -s -B -u -X utf8 "%~dp0packaging\build_release.py" %*
set "BUILD_RC=%ERRORLEVEL%"
goto :finish

:missing
echo ERROR: Bundled Python is missing: "%BUILD_PYTHON%"
set "BUILD_RC=1"

:finish
echo.
if not "%BUILD_RC%"=="0" echo Build stopped with exit code %BUILD_RC%. See the error above.
popd
if /I not "%~1"=="--no-pause" pause
exit /b %BUILD_RC%
