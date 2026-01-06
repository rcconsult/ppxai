# Copy Windows binaries and docs to beta testing folder
# Does NOT overwrite config files (.env, ppxai-config.json)

$sourceDir = "c:\git\utils\ppxai"
$targetDir = "I:\Software\ppxai"

# Create bin subdirectory
$binDir = Join-Path $targetDir "bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

# Copy binaries
Write-Host "Copying binaries..."
Copy-Item "$sourceDir\dist\ppxai.exe" -Destination "$binDir\ppxai.exe" -Force
Copy-Item "$sourceDir\dist\ppxai-server.exe" -Destination "$binDir\ppxai-server.exe" -Force
Copy-Item "$sourceDir\dist\ppxai-desktop.exe" -Destination "$binDir\ppxai-desktop.exe" -Force

# Copy documentation
Write-Host "Copying documentation..."
Copy-Item "$sourceDir\docs\INSTALLATION.md" -Destination "$targetDir\INSTALLATION.md" -Force

# Copy installer script
Write-Host "Copying installer script..."
Copy-Item "$sourceDir\scripts\install.ps1" -Destination "$targetDir\install.ps1" -Force

Write-Host ""
Write-Host "Beta package created at: $targetDir"
Write-Host ""
Get-ChildItem $targetDir -Recurse | Format-Table Mode, LastWriteTime, Length, Name
