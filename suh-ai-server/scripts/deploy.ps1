# SUH AI Server Deployment Script
# This script downloads and deploys the suh-ai-server from GitHub

param(
    [string]$CommitSha = "main",
    [string]$RepoUrl = "https://github.com/Cassiiopeia/suh-project-control",
    [string]$TargetFolder = "C:\AI\suh-ai-server",
    [string]$TempDir = "C:\Temp\suh-deploy"
)

Write-Host "[INFO] Deployment started"
Write-Host "[INFO] Commit SHA: $CommitSha"

# Clean up temp directory
if (Test-Path $TempDir) {
    Write-Host "[INFO] Removing existing temp directory..."
    Remove-Item -Recurse -Force $TempDir
}
New-Item -ItemType Directory -Path $TempDir | Out-Null

# Download source code from GitHub
Write-Host "[INFO] Downloading source code from GitHub..."
$zipUrl = "$RepoUrl/archive/$CommitSha.zip"
$zipPath = Join-Path $TempDir "repo.zip"

try {
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
    Write-Host "[SUCCESS] Download completed"
} catch {
    Write-Host "[ERROR] Download failed: $($_.Exception.Message)"
    exit 1
}

# Extract archive
Write-Host "[INFO] Extracting archive..."
Expand-Archive -Path $zipPath -DestinationPath $TempDir -Force

# Find the extracted folder
$extractedFolder = Get-ChildItem -Path $TempDir -Directory | Select-Object -First 1
$sourceFolder = Join-Path $extractedFolder.FullName "suh-ai-server"

if (-not (Test-Path $sourceFolder)) {
    Write-Host "[ERROR] suh-ai-server folder not found in extracted archive"
    exit 1
}

# Copy files
Write-Host "[INFO] Copying files to $TargetFolder..."

# Create backup if target exists
if (Test-Path $TargetFolder) {
    $backupFolder = "$TargetFolder.backup.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Write-Host "[INFO] Creating backup at $backupFolder..."
    Copy-Item -Path $TargetFolder -Destination $backupFolder -Recurse -Force
}

# Deploy new files
Copy-Item -Path "$sourceFolder\*" -Destination $TargetFolder -Recurse -Force
Write-Host "[SUCCESS] File deployment completed"

# Cleanup
Remove-Item -Recurse -Force $TempDir
Write-Host "[SUCCESS] Deployment finished successfully"
