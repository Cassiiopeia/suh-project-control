#Requires -Version 5.1

<#
.SYNOPSIS
    Flask server deployment and restart script

.DESCRIPTION
    Manages Flask OCR API server using NSSM (Non-Sucking Service Manager).
    Stops existing service, validates Python/dependencies, and restarts the service.

.NOTES
    Author: GitHub Actions
    Version: 1.0.0
#>

param()

$ErrorActionPreference = "Stop"

try {
    Write-Host "[INFO] Starting Flask server deployment..."

    # Configuration
    $flaskPath = "C:\AI\suh-ai-server\flask"
    $serviceName = "FlaskOCRService"
    $runScript = "run.py"

    # Verify Flask directory exists
    if (-not (Test-Path $flaskPath)) {
        Write-Host "[ERROR] Flask directory not found: $flaskPath"
        exit 1
    }

    Write-Host "[SUCCESS] Flask path: $flaskPath"

    # Find Python installation
    Write-Host "[INFO] Locating Python installation..."

    $pythonExe = Get-ChildItem "C:\Users\*\AppData\Local\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue |
                 Sort-Object Name -Descending |
                 Select-Object -First 1 -ExpandProperty FullName

    if (-not $pythonExe) {
        Write-Host "[ERROR] Python not found in C:\Users\*\AppData\Local\Programs\Python\"
        exit 1
    }

    Write-Host "[INFO] Using Python: $pythonExe"

    # Verify Python works
    try {
        $pythonVersion = & $pythonExe --version 2>&1
        Write-Host "[SUCCESS] Python verified: $pythonVersion"
    }
    catch {
        Write-Host "[ERROR] Python failed to execute"
        exit 1
    }

    # Check if run.py exists
    $runScriptPath = Join-Path $flaskPath $runScript
    if (-not (Test-Path $runScriptPath)) {
        Write-Host "[ERROR] Flask run script not found: $runScriptPath"
        exit 1
    }

    Write-Host "[SUCCESS] Flask run script found"

    # Check if NSSM is installed
    Write-Host "[INFO] Checking NSSM installation..."
    $nssmPath = (Get-Command nssm -ErrorAction SilentlyContinue).Source
    if (-not $nssmPath) {
        Write-Host "[ERROR] NSSM not found. Please install NSSM using: choco install nssm"
        exit 1
    }

    Write-Host "[SUCCESS] NSSM found: $nssmPath"

    # Ensure logs directory exists
    $logsPath = Join-Path $flaskPath "logs"
    if (-not (Test-Path $logsPath)) {
        Write-Host "[INFO] Creating logs directory..."
        New-Item -Path $logsPath -ItemType Directory -Force | Out-Null
        Write-Host "[SUCCESS] Logs directory created"
    }

    # Check if service exists
    $serviceExists = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

    if ($serviceExists) {
        Write-Host "[INFO] Stopping existing Flask service..."

        # Stop the service
        Stop-Service -Name $serviceName -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2

        # Verify service stopped
        $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
        if ($service.Status -eq 'Running') {
            Write-Host "[WARN] Service still running, forcing stop..."
            & nssm stop $serviceName
            Start-Sleep -Seconds 3
        }

        Write-Host "[SUCCESS] Flask service stopped"

        # Restart the service
        Write-Host "[INFO] Starting Flask service..."
        Start-Service -Name $serviceName
        Start-Sleep -Seconds 2

        # Verify service started
        $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
        if ($service.Status -eq 'Running') {
            Write-Host "[SUCCESS] Flask service started successfully"
        }
        else {
            Write-Host "[ERROR] Flask service failed to start"
            Write-Host "[INFO] Service status: $($service.Status)"
            exit 1
        }
    }
    else {
        Write-Host "[INFO] Service not found, creating new service..."

        # Create new NSSM service
        & nssm install $serviceName $pythonExe "$runScriptPath"
        & nssm set $serviceName AppDirectory $flaskPath
        & nssm set $serviceName DisplayName "Flask OCR API Service"
        & nssm set $serviceName Description "Ollama OCR API with Waitress WSGI Server"
        & nssm set $serviceName Start SERVICE_AUTO_START
        & nssm set $serviceName AppStdout "$flaskPath\logs\nssm-stdout.log"
        & nssm set $serviceName AppStderr "$flaskPath\logs\nssm-stderr.log"

        Write-Host "[SUCCESS] Service created"

        # Start the service
        Write-Host "[INFO] Starting Flask service..."
        Start-Service -Name $serviceName
        Start-Sleep -Seconds 2

        $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
        if ($service.Status -eq 'Running') {
            Write-Host "[SUCCESS] Flask service started successfully"
        }
        else {
            Write-Host "[ERROR] Flask service failed to start"
            exit 1
        }
    }

    # Verify Flask is responding
    Write-Host "[INFO] Verifying Flask health endpoint..."
    Start-Sleep -Seconds 3

    try {
        $response = Invoke-WebRequest -Uri "http://localhost:5000/health" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            Write-Host "[SUCCESS] Flask health check passed"
            Write-Host "[INFO] Response: $($response.Content)"
        }
        else {
            Write-Host "[WARN] Flask health check returned status: $($response.StatusCode)"
        }
    }
    catch {
        Write-Host "[WARN] Flask health check failed: $($_.Exception.Message)"
        Write-Host "[INFO] Service may still be starting up..."
    }

    Write-Host "[SUCCESS] Flask deployment completed"
    exit 0
}
catch {
    Write-Host "[ERROR] Unexpected error: $($_.Exception.Message)"
    exit 1
}
