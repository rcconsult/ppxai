# Copy Windows binaries and docs to beta testing folder
# Does NOT overwrite config files (.env, ppxai-config.json)
#
# Usage:
#   .\copy-beta.ps1 -TargetDir "I:\Software\ppxai"
#   .\copy-beta.ps1 -TargetDir "D:\beta\ppxai" -SourceDir "C:\my\ppxai"

param(
    [Parameter(Mandatory=$false)]
    [string]$TargetDir,

    [Parameter(Mandatory=$false)]
    [string]$SourceDir
)

# Default source directory to parent of script location
if (-not $SourceDir) {
    $SourceDir = Split-Path -Parent $PSScriptRoot
}

# Prompt for target directory if not provided
if (-not $TargetDir) {
    $TargetDir = Read-Host "Enter destination folder for beta binaries"
    if (-not $TargetDir) {
        Write-Host "Error: Destination folder is required" -ForegroundColor Red
        exit 1
    }
}

# Validate source directory
if (-not (Test-Path "$SourceDir\dist\ppxai.exe")) {
    Write-Host "Error: Binary not found at $SourceDir\dist\ppxai.exe" -ForegroundColor Red
    Write-Host "Run pyinstaller first to build binaries" -ForegroundColor Yellow
    exit 1
}

Write-Host "Source: $SourceDir" -ForegroundColor Cyan
Write-Host "Target: $TargetDir" -ForegroundColor Cyan
Write-Host ""

# Create bin subdirectory
$binDir = Join-Path $TargetDir "bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

# Copy binaries
Write-Host "Copying binaries..."
Copy-Item "$SourceDir\dist\ppxai.exe" -Destination "$binDir\ppxai.exe" -Force
Copy-Item "$SourceDir\dist\ppxai-server.exe" -Destination "$binDir\ppxai-server.exe" -Force
Copy-Item "$SourceDir\dist\ppxai-desktop.exe" -Destination "$binDir\ppxai-desktop.exe" -Force

# Copy documentation
Write-Host "Copying documentation..."
Copy-Item "$SourceDir\docs\INSTALLATION.md" -Destination "$TargetDir\INSTALLATION.md" -Force

# Copy installer script
Write-Host "Copying installer script..."
Copy-Item "$SourceDir\scripts\install.ps1" -Destination "$TargetDir\install.ps1" -Force

Write-Host ""
Write-Host "Beta package created at: $TargetDir" -ForegroundColor Green
Write-Host ""
Get-ChildItem $TargetDir -Recurse | Format-Table Mode, LastWriteTime, Length, Name
