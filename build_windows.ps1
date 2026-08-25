$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot

try {
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $pythonPath = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }

    Write-Host "Verifying release metadata..."
    & $pythonPath tools\verify_release.py

    Write-Host "Installing/building Python dependencies..."
    & $pythonPath -m pip install -r requirements.txt
    & $pythonPath -m pip install pyinstaller

    foreach ($path in @("dist", "build", "installer-dist", "release-dist")) {
        if (Test-Path $path) { Remove-Item $path -Recurse -Force }
    }

    Write-Host "Building ODeR installer payload..."
    & $pythonPath -m PyInstaller build.spec

    Write-Host "Building ODeR Creator installer payload..."
    & $pythonPath -m PyInstaller creator.spec

    $releaseDir = Join-Path $projectRoot "release-dist"
    New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

    $iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
    $isccPath = if ($iscc) { $iscc.Source } else { $null }
    if (-not $isccPath) {
        $innoCandidates = @()
        if (${env:ProgramFiles(x86)}) {
            $innoCandidates += Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
        }
        if ($env:ProgramFiles) {
            $innoCandidates += Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"
        }
        if ($env:LOCALAPPDATA) {
            $innoCandidates += Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
        }
        $isccPath = $innoCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }

    if ($isccPath) {
        Write-Host "Building Inno Setup installer..."
        & $isccPath "installer.iss"
        Write-Host "Installer: release-dist\ODeR Installer.exe"
        & $isccPath "creator_installer.iss"
        Write-Host "Creator installer: release-dist\ODeR Creator Installer.exe"
    } else {
        throw "Inno Setup 6 (iscc.exe) was not found. Install it to create the supported Windows installers."
    }

    $releaseAssets = Get-ChildItem -LiteralPath $releaseDir -File |
        Where-Object { $_.Extension -eq ".exe" } |
        Sort-Object Name
    $checksumLines = foreach ($asset in $releaseAssets) {
        $hash = (Get-FileHash -LiteralPath $asset.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $($asset.Name)"
    }
    $checksumLines | Set-Content -LiteralPath (Join-Path $releaseDir "SHA256SUMS.txt") -Encoding ascii
    Write-Host "Checksums: release-dist\SHA256SUMS.txt"
} finally {
    Pop-Location
}
