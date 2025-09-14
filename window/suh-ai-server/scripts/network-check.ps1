# 한국어 출력을 위한 인코딩 설정
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "   네트워크 및 포트 상태 확인" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# 1. 로컬 IP 확인
Write-Host "[1] 네트워크 정보:" -ForegroundColor Yellow
$localIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.*"}).IPAddress | Select-Object -First 1
Write-Host "   내부 IP: $localIP"

# 외부 IP 확인
try {
    $externalIP = (Invoke-WebRequest -Uri "http://ifconfig.me/ip" -UseBasicParsing -TimeoutSec 5).Content.Trim()
    Write-Host "   외부 IP: $externalIP" -ForegroundColor Green
} catch {
    Write-Host "   외부 IP 확인 실패" -ForegroundColor Red
}
Write-Host ""

# 2. 포트 리스닝 상태
Write-Host "[2] 포트 리스닝 상태:" -ForegroundColor Yellow
$ports = @(11434, 11435, 80)
foreach ($port in $ports) {
    $listening = netstat -an | Select-String ":$port.*LISTENING"
    if ($listening) {
        Write-Host "   포트 $port : 리스닝 중 ✓" -ForegroundColor Green
    } else {
        Write-Host "   포트 $port : 리스닝 안됨 ✗" -ForegroundColor Red
    }
}
Write-Host ""

# 3. 프로세스 상태
Write-Host "[3] 프로세스 상태:" -ForegroundColor Yellow
$processes = @("nginx", "ollama", "cloudflared")
foreach ($proc in $processes) {
    $running = Get-Process -Name $proc -ErrorAction SilentlyContinue
    if ($running) {
        Write-Host "   $proc : 실행 중 ✓" -ForegroundColor Green
        Write-Host "      PID: $($running.Id)" -ForegroundColor Gray
    } else {
        Write-Host "   $proc : 실행 안됨 ✗" -ForegroundColor Red
    }
}
Write-Host ""

# 4. 로컬 연결 테스트
Write-Host "[4] 로컬 연결 테스트:" -ForegroundColor Yellow
$testUrls = @(
    "http://localhost:11435/health",
    "http://127.0.0.1:11435/health"
)

if ($localIP) {
    $testUrls += "http://${localIP}:11435/health"
}

foreach ($url in $testUrls) {
    try {
        $response = Invoke-WebRequest -Uri $url -Method GET -TimeoutSec 3 -UseBasicParsing
        Write-Host "   $url : 성공 ✓ ($($response.StatusCode))" -ForegroundColor Green
    } catch {
        Write-Host "   $url : 실패 ✗" -ForegroundColor Red
    }
}
Write-Host ""

# 5. 터널 상태 확인
Write-Host "[5] Cloudflare 터널 상태:" -ForegroundColor Yellow
$projectRoot = Split-Path -Parent $PSScriptRoot
$tunnelUrlFile = "$projectRoot\data\tunnel_url.txt"

if (Test-Path $tunnelUrlFile) {
    $tunnelUrl = Get-Content $tunnelUrlFile
    Write-Host "   터널 URL: $tunnelUrl" -ForegroundColor Green
    
    # 터널 연결 테스트
    try {
        $response = Invoke-WebRequest -Uri "$tunnelUrl/health" -TimeoutSec 5 -UseBasicParsing
        Write-Host "   터널 상태: 활성 ✓" -ForegroundColor Green
    } catch {
        Write-Host "   터널 상태: 비활성 ✗" -ForegroundColor Red
    }
} else {
    Write-Host "   터널 URL 없음 (터널이 시작되지 않음)" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "        확인 완료" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
