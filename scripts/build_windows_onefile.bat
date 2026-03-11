@echo off
setlocal

powershell -ExecutionPolicy Bypass -File "%~dp0build_windows_onefile.ps1" %*
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
    echo Build failed with exit code %EXIT_CODE%.
)

exit /b %EXIT_CODE%
