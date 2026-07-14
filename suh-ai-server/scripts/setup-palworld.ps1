#Requires -Version 5.1
#Requires -RunAsAdministrator

<#
.SYNOPSIS
    Palworld Dedicated Server 설치 및 NSSM 서비스 등록 (1회 실행)
.DESCRIPTION
    SteamCMD 설치 -> PalServer 설치 -> ini 초기화 -> NSSM 서비스 등록 ->
    방화벽 개방 -> 일일 백업 스케줄러 등록
#>
param(
    [string]$AdminPassword = "palworld-admin-2026",
    [string]$ServerName = "Suh Palworld Server",
    [string]$ServerPassword = ""
)

$ErrorActionPreference = "Stop"

$baseDir = "C:\AI\palworld"
$steamCmdDir = Join-Path $baseDir "steamcmd"
$steamCmdExe = Join-Path $steamCmdDir "steamcmd.exe"
$palServerDir = Join-Path $steamCmdDir "steamapps\common\PalServer"
$palServerExe = Join-Path $palServerDir "PalServer.exe"
# NSSM은 런처(PalServer.exe)가 아닌 Shipping 바이너리를 직접 실행한다.
# 런처는 세션 0(비대화형 서비스) 컨텍스트에서 자식 프로세스를 띄우지 못해 서비스가 즉시 종료된다.
$palServerShippingExe = Join-Path $palServerDir "Pal\Binaries\Win64\PalServer-Win64-Shipping-Cmd.exe"
$configDir = Join-Path $palServerDir "Pal\Saved\Config\WindowsServer"
$iniPath = Join-Path $configDir "PalWorldSettings.ini"
$defaultIniPath = Join-Path $palServerDir "DefaultPalWorldSettings.ini"
$logsDir = Join-Path $baseDir "logs"
$backupDir = Join-Path $baseDir "backups"
$serviceName = "PalServer"

# 1. 디렉토리 생성
foreach ($dir in @($baseDir, $steamCmdDir, $logsDir, $backupDir)) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
}
Write-Host "[SUCCESS] Directories ready: $baseDir"

# 2. SteamCMD 설치
if (-not (Test-Path $steamCmdExe)) {
    Write-Host "[INFO] Downloading SteamCMD..."
    $zipPath = Join-Path $env:TEMP "steamcmd.zip"
    Invoke-WebRequest -Uri "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip" -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $steamCmdDir -Force
    Remove-Item $zipPath
    Write-Host "[SUCCESS] SteamCMD installed"
} else {
    Write-Host "[INFO] SteamCMD already installed"
}

# 3. PalServer 설치/업데이트 (수 GB 다운로드 - 시간 소요)
Write-Host "[INFO] Installing/updating Palworld Dedicated Server (app 2394010)..."
& $steamCmdExe +login anonymous +app_update 2394010 validate +quit
if (-not (Test-Path $palServerExe)) {
    Write-Host "[ERROR] PalServer.exe not found after install: $palServerExe"
    exit 1
}
Write-Host "[SUCCESS] PalServer installed: $palServerDir"

# 4. ini 초기화 (DefaultPalWorldSettings.ini 복사 후 값 수정)
if (-not (Test-Path $configDir)) { New-Item -ItemType Directory -Force -Path $configDir | Out-Null }
if (-not (Test-Path $iniPath)) {
    if (-not (Test-Path $defaultIniPath)) {
        Write-Host "[ERROR] DefaultPalWorldSettings.ini not found: $defaultIniPath"
        exit 1
    }
    Copy-Item $defaultIniPath $iniPath
    Write-Host "[SUCCESS] PalWorldSettings.ini created from default"
}

# OptionSettings 라인의 주요 값 수정 (서버 정지 상태에서만 실행되므로 안전)
$content = Get-Content $iniPath -Raw
$replacements = @{
    'ServerName="[^"]*"'      = "ServerName=`"$ServerName`""
    'AdminPassword="[^"]*"'   = "AdminPassword=`"$AdminPassword`""
    'ServerPassword="[^"]*"'  = "ServerPassword=`"$ServerPassword`""
    'RESTAPIEnabled=\w+'      = 'RESTAPIEnabled=True'
    'RESTAPIPort=\d+'         = 'RESTAPIPort=8212'
}
foreach ($pattern in $replacements.Keys) {
    $content = $content -replace $pattern, $replacements[$pattern]
}
Set-Content -Path $iniPath -Value $content -NoNewline -Encoding UTF8
Write-Host "[SUCCESS] ini configured (RESTAPIEnabled=True, RESTAPIPort=8212)"

# 5. NSSM 서비스 등록
$nssmPath = (Get-Command nssm -ErrorAction SilentlyContinue).Source
if (-not $nssmPath) {
    Write-Host "[ERROR] NSSM not found. Install with: choco install nssm"
    exit 1
}
$existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
# -log: 언리얼 엔진이 Pal\Saved\Logs\Pal.log 파일을 디스크에 기록하도록 강제한다.
# 이 플래그가 없으면 엔진 로그는 콘솔(GLog)로만 흘러 Pal.log가 아예 생성되지 않는다.
$palServerArgs = "-port=8211 -players=32 -log -useperfthreads -NoAsyncLoadingThread -UseMultithreadForDS"
if (-not $existing) {
    & nssm install $serviceName $palServerShippingExe $palServerArgs
    Write-Host "[SUCCESS] NSSM service '$serviceName' created"
} else {
    & nssm set $serviceName Application $palServerShippingExe
    & nssm set $serviceName AppParameters $palServerArgs
    Write-Host "[INFO] Service '$serviceName' already exists - reapplying configuration"
}

# Apply configuration on every run (both new and existing services)
& nssm set $serviceName AppDirectory $palServerDir
& nssm set $serviceName DisplayName "Palworld Dedicated Server"
& nssm set $serviceName Start SERVICE_AUTO_START
& nssm set $serviceName AppStdout "$logsDir\palserver-stdout.log"
& nssm set $serviceName AppStderr "$logsDir\palserver-stderr.log"
& nssm set $serviceName AppStopMethodConsole 15000
# 로그 로테이션: stdout/stderr가 10MB 넘으면 회전 (무한 성장 방지)
& nssm set $serviceName AppRotateFiles 1
& nssm set $serviceName AppRotateOnline 1
& nssm set $serviceName AppRotateBytes 10485760

# 6. 방화벽 개방 (UDP 8211 게임, UDP 27015 스팀 서버목록)
foreach ($rule in @(
    @{ Name = "Palworld-Game-8211";  Port = 8211  },
    @{ Name = "Palworld-Steam-27015"; Port = 27015 }
)) {
    if (-not (Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Protocol UDP -LocalPort $rule.Port -Action Allow | Out-Null
        Write-Host "[SUCCESS] Firewall rule added: $($rule.Name)"
    }
}

# 7. 일일 백업 스케줄러 (매일 04:00, robocopy 미러가 아닌 신규 폴더 복사)
$taskName = "PalworldDailyBackup"
if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
    $saveDir = Join-Path $palServerDir "Pal\Saved\SaveGames"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
        "-NoProfile -Command `"robocopy '$saveDir' ('$backupDir\' + (Get-Date -Format yyyyMMdd_HHmmss)) /E`"" )
    $trigger = New-ScheduledTaskTrigger -Daily -At 4am
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -RunLevel Highest | Out-Null
    Write-Host "[SUCCESS] Daily backup task registered (04:00)"
}

# 8. 서비스 시작 및 REST API 검증
Write-Host "[INFO] Starting PalServer service..."
Start-Service -Name $serviceName
Start-Sleep -Seconds 30

$pair = "admin:$AdminPassword"
$headers = @{ Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair)) }
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8212/v1/api/info" -Headers $headers -TimeoutSec 10
    Write-Host "[SUCCESS] Palworld REST API responding: $($resp | ConvertTo-Json -Compress)"
} catch {
    Write-Host "[WARN] REST API not responding yet (server may still be loading): $($_.Exception.Message)"
}
Write-Host "[SUCCESS] setup-palworld.ps1 completed"
