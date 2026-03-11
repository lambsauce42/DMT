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
$appIconPng = Join-Path $assetsDir "DMT.png"
$appIconIco = Join-Path $assetsDir "DMT.ico"

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

$pyInstallerIcon = $null
if (Test-Path $appIconIco) {
    $pyInstallerIcon = $appIconIco
}
elseif (Test-Path $appIconPng) {
    $generatedIcon = Join-Path $workDir "DMT.generated.ico"
    & $Python -c "import PIL" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Pillow not found for icon conversion. Installing..." -ForegroundColor Yellow
        & $Python -m pip install pillow
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install Pillow for Windows icon generation."
        }
    }
    $iconScriptPath = Join-Path $workDir "generate_app_icon.py"
    $iconScript = @'
from pathlib import Path
from PIL import Image
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
image = Image.open(source)
target.parent.mkdir(parents=True, exist_ok=True)
image.save(
    target,
    sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)],
)
'@
    Set-Content -Path $iconScriptPath -Value $iconScript -Encoding UTF8
    & $Python $iconScriptPath $appIconPng $generatedIcon
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $generatedIcon)) {
        throw "Failed to generate Windows icon from $appIconPng"
    }
    $pyInstallerIcon = $generatedIcon
}

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
    "--hidden-import", "soundcard"
)

if ($pyInstallerIcon) {
    $pyInstallerArgs += @("--icon", $pyInstallerIcon)
}

$pyInstallerArgs += $appEntry

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
