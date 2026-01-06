# Install ppxai binaries locally
$targetDir = Join-Path $env:USERPROFILE ".ppxai\bin"
$distDir = "c:\git\utils\ppxai\dist"

# Stop running server if any
$serverProc = Get-Process -Name 'ppxai-server' -ErrorAction SilentlyContinue
if ($serverProc) {
    Write-Host "Stopping ppxai-server..."
    $serverProc | Stop-Process -Force
    Start-Sleep -Seconds 2
}

# Create target directory
New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

# Copy binaries
Copy-Item "$distDir\ppxai.exe" -Destination "$targetDir\ppxai.exe" -Force
Copy-Item "$distDir\ppxai-server.exe" -Destination "$targetDir\ppxai-server.exe" -Force
Copy-Item "$distDir\ppxai-desktop.exe" -Destination "$targetDir\ppxai-desktop.exe" -Force

Write-Host "Installed to: $targetDir"
Get-ChildItem $targetDir -Filter "*.exe"
