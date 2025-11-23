#Requires -Version 5.1

<#
.SYNOPSIS
    Nginx configuration deployment and restart script

.DESCRIPTION
    Copies C:\AI\suh-ai-server\config\nginx.conf to Nginx installation path,
    validates the configuration, and performs zero-downtime reload.

.NOTES
    Author: GitHub Actions
    Version: 1.0.0
#>

param()

$ErrorActionPreference = "Stop"

try {
    Write-Host "[INFO] Searching for Nginx installation..."

    # Find Nginx path (Chocolatey installation)
    $nginxPath = Get-ChildItem "C:\tools" -Directory -Filter "nginx-*" -ErrorAction SilentlyContinue |
        Where-Object { Test-Path "$($_.FullName)\nginx.exe" } |
        Select-Object -First 1 -ExpandProperty FullName

    if (-not $nginxPath) {
        Write-Host "[ERROR] Nginx not found"
        exit 1
    }

    Write-Host "[SUCCESS] Nginx path: $nginxPath"

    # Create backup
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $confPath = Join-Path $nginxPath "conf\nginx.conf"
    $backupPath = "$confPath.backup.$timestamp"

    if (Test-Path $confPath) {
        Copy-Item $confPath $backupPath -ErrorAction SilentlyContinue
        Write-Host "[INFO] Backup created: $backupPath"
    }

    # Copy new configuration
    Copy-Item "C:\AI\suh-ai-server\config\nginx.conf" $confPath -Force
    Write-Host "[SUCCESS] Configuration file deployed"

    # Validate configuration
    if ([string]::IsNullOrEmpty($nginxPath)) {
        Write-Host "[ERROR] Nginx path is null or empty"
        exit 1
    }

    $nginxExe = "$nginxPath\nginx.exe"

    if (-not (Test-Path $nginxExe)) {
        Write-Host "[ERROR] nginx.exe not found at: $nginxExe"
        exit 1
    }

    Write-Host "[INFO] Validating Nginx configuration..."
    Write-Host "[DEBUG] Nginx executable: $nginxExe"

    # Use Start-Process to handle paths with spaces
    $testProcess = Start-Process -FilePath $nginxExe -ArgumentList "-t" -WorkingDirectory $nginxPath -NoNewWindow -Wait -PassThru -RedirectStandardError "$env:TEMP\nginx-test-error.txt" -RedirectStandardOutput "$env:TEMP\nginx-test-output.txt"

    $testOutput = Get-Content "$env:TEMP\nginx-test-output.txt" -ErrorAction SilentlyContinue
    $testError = Get-Content "$env:TEMP\nginx-test-error.txt" -ErrorAction SilentlyContinue

    if ($testOutput) { Write-Host $testOutput }
    if ($testError) { Write-Host $testError }

    if ($testProcess.ExitCode -ne 0) {
        Write-Host "[ERROR] Configuration validation failed - rolling back..."
        if (Test-Path $backupPath) {
            Copy-Item $backupPath $confPath -Force
            Write-Host "[SUCCESS] Rolled back to previous configuration"
        }
        exit 1
    }

    Write-Host "[SUCCESS] Configuration validation passed"

    # Zero-downtime restart
    $nginxProcess = Get-Process nginx -ErrorAction SilentlyContinue
    if ($nginxProcess) {
        Write-Host "[INFO] Reloading Nginx..."
        Write-Host "[DEBUG] Executing: $nginxExe -s reload"
        $reloadProcess = Start-Process -FilePath $nginxExe -ArgumentList "-s", "reload" -WorkingDirectory $nginxPath -NoNewWindow -Wait -PassThru

        if ($reloadProcess.ExitCode -eq 0) {
            Write-Host "[SUCCESS] Nginx reloaded"
        }
        else {
            Write-Host "[WARN] Reload failed - attempting restart..."
            Stop-Process -Name nginx -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            Write-Host "[DEBUG] Starting: $nginxExe"
            Start-Process -FilePath $nginxExe -WorkingDirectory $nginxPath -WindowStyle Hidden
            Write-Host "[SUCCESS] Nginx restarted"
        }
    }
    else {
        Write-Host "[INFO] Starting Nginx..."
        Write-Host "[DEBUG] Starting: $nginxExe"
        Start-Process -FilePath $nginxExe -WorkingDirectory $nginxPath -WindowStyle Hidden
        Write-Host "[SUCCESS] Nginx started"
    }

    Write-Host "[SUCCESS] Nginx deployment completed"
    exit 0
}
catch {
    Write-Host "[ERROR] Unexpected error: $($_.Exception.Message)"
    exit 1
}
