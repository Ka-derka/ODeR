$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot

try {
    Write-Host "Installing/building Python dependencies..."
    python -m pip install -r requirements.txt
    python -m pip install pyinstaller

    foreach ($path in @("dist", "build", "installer-dist", "release-dist")) {
        if (Test-Path $path) { Remove-Item $path -Recurse -Force }
    }

    Write-Host "Building portable single-file executable..."
    python -m PyInstaller build.spec

    $releaseDir = Join-Path $projectRoot "release-dist"
    $portableStage = Join-Path $releaseDir "ODeR-Portable"
    New-Item -ItemType Directory -Path $portableStage -Force | Out-Null
    $portableExe = Join-Path $releaseDir "ODeR-Portable.exe"
    Copy-Item "dist\ODeR-Portable.exe" $portableExe
    Copy-Item $portableExe $portableStage
    Copy-Item "portable.flag" $portableStage
    Copy-Item "LICENSE" $portableStage
    Copy-Item "THIRD_PARTY_NOTICES.md" $portableStage

    $portableZip = Join-Path $releaseDir "ODeR-Portable.zip"
    Compress-Archive -Path (Join-Path $portableStage "*") -DestinationPath $portableZip -CompressionLevel Optimal
    Remove-Item $portableStage -Recurse -Force
    Write-Host "Portable executable: release-dist\ODeR-Portable.exe"
    Write-Host "Portable package: release-dist\ODeR-Portable.zip"

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
    } else {
        Write-Host "Inno Setup 6 (iscc.exe) was not found; the installer was skipped."
        Write-Host "Install Inno Setup 6 and run this script again to create ODeR Installer.exe."
    }

    $releaseAssets = Get-ChildItem -LiteralPath $releaseDir -File |
        Where-Object { $_.Extension -in @(".zip", ".exe") } |
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
