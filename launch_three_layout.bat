@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS1_PATH=%SCRIPT_DIR%launch_three_layout.ps1"

if not exist "%PS1_PATH%" (
  echo Could not find %PS1_PATH%
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1_PATH%" -RepoPath "%SCRIPT_DIR%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo Launcher failed with exit code %EXIT_CODE%.
  exit /b %EXIT_CODE%
)

exit /b 0
