$ErrorActionPreference = "Stop"

Write-Host "Installing/building Python dependencies..."
python -m pip install -r requirements.txt
python -m pip install pyinstaller

if (Test-Path dist) { Remove-Item dist -Recurse -Force }
if (Test-Path build) { Remove-Item build -Recurse -Force }

Write-Host "Building single-file executable..."
python -m PyInstaller build.spec

Write-Host "Standalone build: dist\OfflineDirectoryBrowser.exe"

$iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
if ($iscc) {
    Write-Host "Building optional Inno Setup installer..."
    & $iscc.Source installer.iss
    Write-Host "Installer: installer-dist\OfflineDirectoryBrowser-Setup.exe"
} else {
    Write-Host "Inno Setup (iscc.exe) not found; skipping installer build."
    Write-Host "The standalone exe is still ready to use as a portable build."
}
