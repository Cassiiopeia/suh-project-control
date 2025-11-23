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

    # Dynamically find Python installation
    Write-Host "[INFO] Searching for Python installation..."
    $pythonExe = $null

    # Method 1: Try common Python installation paths (ordered by preference)
    $pythonPaths = @(
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe",
        "C:\Python39\python.exe",
        "C:\Python38\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
    )

    foreach ($path in $pythonPaths) {
        if (Test-Path $path) {
            $pythonExe = $path
            Write-Host "[INFO] Found Python at: $pythonExe"
            break
        }
    }

    # Method 2: Try PATH environment variable
    if (-not $pythonExe) {
        try {
            $pythonCmd = Get-Command python -ErrorAction Stop
            $pythonExe = $pythonCmd.Source
            Write-Host "[INFO] Found Python in PATH: $pythonExe"
        }
        catch {
            # Python not in PATH, continue
        }
    }

    # Method 3: Search C:\ for Python installations
    if (-not $pythonExe) {
        Write-Host "[INFO] Searching C:\ for Python installations..."
        $foundPythons = Get-ChildItem -Path "C:\" -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue -Depth 2 |
            Where-Object { $_.FullName -match "Python\d+" } |
            Sort-Object { $_.FullName } -Descending |
            Select-Object -First 1

        if ($foundPythons) {
            $pythonExe = $foundPythons.FullName
            Write-Host "[INFO] Found Python via search: $pythonExe"
        }
    }

    # Verify Python was found and is working
    if (-not $pythonExe -or -not (Test-Path $pythonExe)) {
        Write-Host "[ERROR] Python installation not found. Please install Python 3.8 or higher."
        Write-Host "[ERROR] Searched paths:"
        $pythonPaths | ForEach-Object { Write-Host "  - $_" }
        exit 1
    }

    # Verify Python works
    try {
        $pythonVersion = & $pythonExe --version 2>&1
        Write-Host "[SUCCESS] Python found and verified: $pythonVersion"
        Write-Host "[INFO] Python executable: $pythonExe"
    }
    catch {
        Write-Host "[ERROR] Python found but failed to execute: $pythonExe"
        Write-Host "[ERROR] Error: $($_.Exception.Message)"
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
