#Requires -Version 5.1
#Requires -RunAsAdministrator

<#
.SYNOPSIS
    gbrain HTTP 서버(MCP) 설치 및 NSSM 서비스 등록 (다시 실행해도 같은 결과)
    개인 브레인: 기본값 그대로 (gbrain-http, 3131) / 팀 브레인(#210): 관제소가 -SkipInstall 과 브레인별 값으로 호출
.DESCRIPTION
    bun 확인 -> gbrain 고정 커밋 설치 -> 설정 파일 확인 -> 관리자 토큰(없을 때만 생성) ->
    실행기 복사 -> NSSM 서비스 등록·갱신 -> 기동 후 /health 확인
    값을 바꾸면 함께 바꿀 곳: flask/config/gbrain_server_config.py, config/nginx.conf(gbrain_backend),
    flask/config/control_tower/services.yml(gbrain-mcp)
#>
param(
    # 맥과 같은 gbrain 빌드 (0.60.739.0 = 커밋 6297783)
    [string]$GbrainCommit = "6297783",
    # gbrain 설정 루트: {GbrainHome}\.gbrain\config.json, bun 도 {GbrainHome}\.bun 에 설치
    [string]$GbrainHome = "C:\Users\kimchi",
    [int]$Port = 3131,
    [string]$ServiceName = "gbrain-http",
    # 이미 설치된 gbrain 을 그대로 쓰고 서비스만 갱신
    [switch]$SkipInstall,
    # bun·gbrain 설치 위치 ({BunHome}\.bun): 팀 브레인은 개인 브레인 설치를 같이 씀 (기본 = GbrainHome)
    [string]$BunHome = "",
    # 브레인별 관리자 토큰·로그 (기본 = 개인 브레인 경로)
    [string]$AdminTokenPath = "C:\AI\secrets\gbrain-admin-bootstrap-token",
    [string]$LogPath = "C:\AI\gbrain\logs\gbrain-http.log",
    [string]$DisplayName = "gbrain HTTP MCP server"
)

$ErrorActionPreference = "Stop"

if (-not $BunHome) { $BunHome = $GbrainHome }
$baseDir = "C:\AI\gbrain"
$logPath = $LogPath
$logsDir = Split-Path $logPath
# 실행기는 모든 브레인이 같이 씀 (값은 서비스별 AppEnvironmentExtra 로 받음)
$launcherSource = Join-Path $PSScriptRoot "gbrain\run-gbrain-http.cmd"
$launcherPath = Join-Path $baseDir "run-gbrain-http.cmd"
$adminTokenPath = $AdminTokenPath
$secretsDir = Split-Path $adminTokenPath
$bunDir = Join-Path $BunHome ".bun"
$bunExe = Join-Path $bunDir "bin\bun.exe"
$gbrainCliPath = Join-Path $bunDir "install\global\node_modules\gbrain\src\cli.ts"
$gbrainConfigPath = Join-Path $GbrainHome ".gbrain\config.json"

# 1. NSSM 확인
$nssm = (Get-Command nssm -ErrorAction SilentlyContinue).Source
if (-not $nssm) { throw "NSSM not found. Install it with: choco install nssm" }

# 2. 디렉토리 (실행기·로그는 배포가 덮어쓰는 C:\AI\suh-ai-server 밖)
foreach ($dir in @($baseDir, $logsDir, $secretsDir)) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
}

# 3. bun + gbrain 설치 (BUN_INSTALL 로 위치 고정: 서비스는 LocalSystem 이라 프로필 경로가 다름)
if (-not $SkipInstall) {
    $env:BUN_INSTALL = $bunDir
    if (-not (Test-Path $bunExe)) {
        $zipPath = Join-Path $env:TEMP "bun-windows-x64.zip"
        $extractDir = Join-Path $env:TEMP "bun-windows-x64-extract"
        Invoke-WebRequest -UseBasicParsing "https://github.com/oven-sh/bun/releases/latest/download/bun-windows-x64.zip" -OutFile $zipPath
        Expand-Archive -Force $zipPath $extractDir
        New-Item -ItemType Directory -Force -Path (Split-Path $bunExe) | Out-Null
        Copy-Item -Force (Join-Path $extractDir "bun-windows-x64\bun.exe") $bunExe
    }
    # bun 은 진행 표시를 stderr 로 내므로 종료 코드로만 판단
    $ErrorActionPreference = "Continue"
    & $bunExe install -g "github:garrytan/gbrain#$GbrainCommit" 2>&1 | Select-Object -Last 3 | Out-String | Write-Host
    $installExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($installExitCode -ne 0) { throw "gbrain install failed (exit $installExitCode)" }
}
if (-not (Test-Path $gbrainCliPath)) { throw "gbrain cli not found: $gbrainCliPath" }

# 4. 설정 파일 확인 (DB 비번 포함 > 소유자·SYSTEM·Administrators 만)
if (-not (Test-Path $gbrainConfigPath)) {
    throw "gbrain config missing: $gbrainConfigPath (engine postgres, database_url 127.0.0.1:5433/gbrain, embedding ollama)"
}
# 실행 계정이 SYSTEM(관제소 호출)이면 사용자 권한은 붙이지 않음 (계정 이름이 컴퓨터명$)
$configGrants = @("SYSTEM:F", "Administrators:F")
if (-not $env:USERNAME.EndsWith('$')) { $configGrants += "$($env:USERNAME):F" }
& icacls $gbrainConfigPath /inheritance:r /grant:r @configGrants | Out-Null

# 5. 관리자 토큰: 없을 때만 생성 (gbrain 규칙 32자 이상 [A-Za-z0-9_-]), 값은 출력하지 않음
if (-not (Test-Path $adminTokenPath)) {
    $randomBytes = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($randomBytes)
    $adminToken = [Convert]::ToBase64String($randomBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    # BOM 없는 한 줄 (실행기의 set /p 가 첫 줄을 그대로 읽음)
    [IO.File]::WriteAllText($adminTokenPath, $adminToken)
    Write-Host "[SUCCESS] Admin token created: $adminTokenPath"
} else {
    Write-Host "[INFO] Admin token kept: $adminTokenPath"
}
& icacls $adminTokenPath /inheritance:r /grant:r "SYSTEM:F" "Administrators:F" | Out-Null

# 6. 실행기 복사 (레포 원본 > C:\AI\gbrain), 내용이 같으면 건너뜀 (다른 브레인 서비스가 실행 중인 cmd 파일 교체 방지)
$isLauncherCurrent = (Test-Path $launcherPath) -and ((Get-FileHash $launcherSource).Hash -eq (Get-FileHash $launcherPath).Hash)
if (-not $isLauncherCurrent) { Copy-Item -Force $launcherSource $launcherPath }

# 7. NSSM 서비스 등록·갱신
# 정지: NSSM 2.24 가 bun 종료 후 StopPending 에 멈추는 경우가 있어 8초 뒤 래퍼 강제 종료
# (관제소 util/windows_service_client.py FORCED_STOP_SCRIPT 와 같은 방식)
if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    Stop-Service -Name $ServiceName -NoWait -ErrorAction SilentlyContinue
    $deadline = (Get-Date).AddSeconds(8)
    while ((Get-Service $ServiceName).Status -ne 'Stopped' -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
    if ((Get-Service $ServiceName).Status -ne 'Stopped') {
        $wrapperProcessId = (Get-CimInstance Win32_Service -Filter "Name='$ServiceName'").ProcessId
        if ($wrapperProcessId -gt 0) { Stop-Process -Id $wrapperProcessId -Force }
        Start-Sleep -Seconds 3
    }
} else {
    & $nssm install $ServiceName "C:\Windows\System32\cmd.exe" | Out-Null
}
& $nssm set $ServiceName Application "C:\Windows\System32\cmd.exe" | Out-Null
& $nssm set $ServiceName AppParameters "/c `"$launcherPath`"" | Out-Null
& $nssm set $ServiceName AppDirectory $baseDir | Out-Null
& $nssm set $ServiceName AppEnvironmentExtra `
    "GBRAIN_HOME=$GbrainHome" "HOME=$GbrainHome" "USERPROFILE=$GbrainHome" `
    "PATH=$bunDir\bin;C:\Windows\System32;C:\Windows" `
    "GBRAIN_ADMIN_TOKEN_FILE=$adminTokenPath" "GBRAIN_BUN_EXE=$bunExe" `
    "GBRAIN_CLI_PATH=$gbrainCliPath" "GBRAIN_PORT=$Port" | Out-Null
& $nssm set $ServiceName AppStdout $logPath | Out-Null
& $nssm set $ServiceName AppStderr $logPath | Out-Null
& $nssm set $ServiceName AppRotateFiles 1 | Out-Null
& $nssm set $ServiceName AppRotateOnline 1 | Out-Null
& $nssm set $ServiceName AppRotateBytes 10485760 | Out-Null
& $nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null
& $nssm set $ServiceName AppExit Default Restart | Out-Null
# 재시작 지연 0: 5000 이면 정지가 StopPending 에 더 자주 멈춤 (다른 NSSM 서비스와 동일)
& $nssm set $ServiceName AppRestartDelay 0 | Out-Null
& $nssm set $ServiceName DisplayName $DisplayName | Out-Null
& $nssm set $ServiceName Description "gbrain serve --http on 127.0.0.1:$Port (GBRAIN_HOME $GbrainHome, public MCP via nginx)" | Out-Null

# 8. 기동 > /health 확인 (DB 연결까지 최대 60초)
& $nssm start $ServiceName | Out-Null
$health = $null
for ($attempt = 0; $attempt -lt 30 -and -not $health; $attempt++) {
    Start-Sleep -Seconds 2
    try { $health = Invoke-RestMethod -UseBasicParsing "http://127.0.0.1:$Port/health" -TimeoutSec 5 } catch { $health = $null }
}
if (-not $health) { throw "gbrain-http did not become healthy. Check $logPath" }
Write-Host "[SUCCESS] $ServiceName healthy: version $($health.version), engine $($health.engine)"
