param(
    [string]$Python = "python",
    [switch]$InstallBuildDeps
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$srcDir = Join-Path $repoRoot "src"
$appEntry = Join-Path $srcDir "app.py"
$assetsDir = Join-Path $repoRoot "assets"
$dataDir = Join-Path $repoRoot "data"
$distDir = Join-Path $repoRoot "dist\windows-onefile"
$workDir = Join-Path $repoRoot "build\pyinstaller"

if ($env:OS -ne "Windows_NT") {
    throw "This script must be run from Windows PowerShell. Build the .exe with Windows Python, not WSL."
}

if (-not (Test-Path $appEntry)) {
    throw "Missing app entrypoint: $appEntry"
}

if ($InstallBuildDeps) {
    & $Python -m pip install --upgrade pip pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install PyInstaller build dependencies."
    }
}

if (Test-Path $distDir) {
    Remove-Item $distDir -Recurse -Force
}
New-Item -ItemType Directory -Path $distDir -Force | Out-Null
New-Item -ItemType Directory -Path $workDir -Force | Out-Null

$pyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onefile",
    "--name", "DMT",
    "--distpath", $distDir,
    "--workpath", $workDir,
    "--specpath", $workDir,
    "--paths", $srcDir,
    "--add-data", "$assetsDir;assets",
    "--add-data", "$dataDir;data",
    "--collect-all", "PySide6",
    "--collect-all", "pypdfium2",
    "--hidden-import", "PySide6.QtSvg",
    "--hidden-import", "PySide6.QtMultimedia",
    "--hidden-import", "PySide6.QtNetwork",
    "--hidden-import", "soundcard",
    $appEntry
)

Push-Location $repoRoot
try {
    & $Python @pyInstallerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }
}
finally {
    Pop-Location
}

$exePath = Join-Path $distDir "DMT.exe"
if (-not (Test-Path $exePath)) {
    throw "Build finished without producing $exePath"
}

Write-Host ""
Write-Host "Built executable:" -ForegroundColor Green
Write-Host $exePath
