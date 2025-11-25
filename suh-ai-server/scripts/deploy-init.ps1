# SUH AI Server Deployment Script
# This script downloads and deploys the suh-ai-server from GitHub

param(
    [string]$CommitSha = "main",
    [string]$RepoUrl = "https://github.com/Cassiiopeia/suh-project-control",
    [string]$TargetFolder = "C:\AI\suh-ai-server",
    [string]$TempDir = "C:\Temp\suh-deploy",
    [switch]$GitHubAction
)

Write-Host "[INFO] Deployment started"
Write-Host "[INFO] Commit SHA: $CommitSha"

# Backup nginx.conf if it exists and has been modified by GitHub Actions
# This needs to be done before any file operations to preserve API keys
$nginxConfBackup = $null
$nginxConfPath = Join-Path $TargetFolder "config\nginx.conf"
if (Test-Path $nginxConfPath) {
    $nginxContent = Get-Content $nginxConfPath -Raw
    # Check if API keys have been injected (no placeholder remaining)
    if ($nginxContent -notmatch '\{\{OLLAMA_API_KEY_LIST\}\}') {
        Write-Host "[INFO] Preserving nginx.conf with injected API keys..."
        $nginxConfBackup = $nginxContent
    }
}

if ($GitHubAction) {
    # GitHub Actions: Files already uploaded via SCP, skip download and file operations
    Write-Host "[INFO] Running in GitHub Actions - skipping download (files already uploaded via SCP)"
} else {
    # Local execution: Download from GitHub and deploy files
    Write-Host "[INFO] Running locally - will download from GitHub"
    
    # Step 1: Clean up temp directory
    if (Test-Path $TempDir) {
        Write-Host "[INFO] Removing existing temp directory..."
        Remove-Item -Recurse -Force $TempDir
    }
    New-Item -ItemType Directory -Path $TempDir | Out-Null
    
    # Step 2: Download source code from GitHub
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
    
    # Step 3: Extract archive
    Write-Host "[INFO] Extracting archive..."
    Expand-Archive -Path $zipPath -DestinationPath $TempDir -Force
    
    # Step 4: Find the extracted folder
    $extractedFolder = Get-ChildItem -Path $TempDir -Directory | Select-Object -First 1
    $sourceFolder = Join-Path $extractedFolder.FullName "suh-ai-server"

    if (-not (Test-Path $sourceFolder)) {
        Write-Host "[ERROR] suh-ai-server folder not found in extracted archive"
        exit 1
    }
    
    # Step 5: Deploy new files
    Write-Host "[INFO] Copying files to $TargetFolder..."
    Copy-Item -Path "$sourceFolder\*" -Destination $TargetFolder -Recurse -Force
    
    # Step 6: Cleanup temp directory
    Remove-Item -Recurse -Force $TempDir
    Write-Host "[SUCCESS] Temp directory cleaned up"
}

# Restore nginx.conf with injected API keys (if backup exists)
# This applies to both GitHub Actions and local execution
if ($nginxConfBackup) {
    Set-Content -Path $nginxConfPath -Value $nginxConfBackup -NoNewline
    Write-Host "[SUCCESS] Restored nginx.conf with API keys"
}

Write-Host "[SUCCESS] File deployment completed"

Write-Host "[SUCCESS] Deployment finished successfully"
