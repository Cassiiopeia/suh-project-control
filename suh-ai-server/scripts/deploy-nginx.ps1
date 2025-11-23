#Requires -Version 5.1

<#
.SYNOPSIS
    Nginx 설정 파일 배포 및 재시작 스크립트

.DESCRIPTION
    C:\AI\suh-ai-server\config\nginx.conf를 Nginx 설치 경로로 복사하고
    설정을 검증한 후 무중단 재시작(reload)를 수행합니다.

.NOTES
    작성자: GitHub Actions
    버전: 1.0.0
#>

param()

$ErrorActionPreference = "Stop"

try {
    Write-Host "[INFO] Searching for Nginx installation..."

    # Nginx 경로 찾기 (Chocolatey 설치 기준)
    $nginxPath = Get-ChildItem "C:\tools" -Directory -Filter "nginx-*" -ErrorAction SilentlyContinue |
        Where-Object { Test-Path "$($_.FullName)\nginx.exe" } |
        Select-Object -First 1 -ExpandProperty FullName

    if (-not $nginxPath) {
        Write-Host "[ERROR] Nginx not found"
        exit 1
    }

    Write-Host "[SUCCESS] Nginx path: $nginxPath"

    # 백업 생성
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $confPath = Join-Path $nginxPath "conf\nginx.conf"
    $backupPath = "$confPath.backup.$timestamp"

    if (Test-Path $confPath) {
        Copy-Item $confPath $backupPath -ErrorAction SilentlyContinue
        Write-Host "[INFO] Backup created: $backupPath"
    }

    # 새 설정 복사
    Copy-Item "C:\AI\suh-ai-server\config\nginx.conf" $confPath -Force
    Write-Host "[SUCCESS] Configuration file deployed"

    # 설정 검증
    $nginxExe = Join-Path $nginxPath "nginx.exe"
    Write-Host "[INFO] Validating Nginx configuration..."

    # 경로에 공백이 있을 수 있으므로 Start-Process 사용
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

    # 무중단 재시작
    $nginxProcess = Get-Process nginx -ErrorAction SilentlyContinue
    if ($nginxProcess) {
        Write-Host "[INFO] Reloading Nginx..."
        $reloadProcess = Start-Process -FilePath $nginxExe -ArgumentList "-s", "reload" -WorkingDirectory $nginxPath -NoNewWindow -Wait -PassThru

        if ($reloadProcess.ExitCode -eq 0) {
            Write-Host "[SUCCESS] Nginx reloaded"
        }
        else {
            Write-Host "[WARN] Reload failed - attempting restart..."
            Stop-Process -Name nginx -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            Start-Process -FilePath $nginxExe -WorkingDirectory $nginxPath -WindowStyle Hidden
            Write-Host "[SUCCESS] Nginx restarted"
        }
    }
    else {
        Write-Host "[INFO] Starting Nginx..."
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
