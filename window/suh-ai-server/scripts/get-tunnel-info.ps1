# 한국어 출력을 위한 인코딩 설정
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$projectRoot = Split-Path -Parent $PSScriptRoot
$dataDir = "$projectRoot\data"
$urlFile = "$dataDir\tunnel_url.txt"
$infoFile = "$dataDir\tunnel_info.json"

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "   현재 터널 정보" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# URL 파일 확인
if (Test-Path $urlFile) {
    $url = Get-Content $urlFile
    Write-Host "터널 URL:" -ForegroundColor Yellow
    Write-Host $url -ForegroundColor Green
    Write-Host ""
    
    # 클립보드에 복사
    try {
        $url | Set-Clipboard
        Write-Host "✓ URL이 클립보드에 복사되었습니다!" -ForegroundColor Cyan
    } catch {
        Write-Host "⚠ 클립보드 복사 실패" -ForegroundColor Yellow
    }
} else {
    Write-Host "터널 URL을 찾을 수 없습니다." -ForegroundColor Red
    Write-Host "먼저 start-tunnel.bat을 실행해주세요." -ForegroundColor Yellow
}

# 정보 파일 확인
if (Test-Path $infoFile) {
    Write-Host ""
    Write-Host "상세 정보:" -ForegroundColor Yellow
    try {
        $info = Get-Content $infoFile | ConvertFrom-Json
        Write-Host "생성 시간: $($info.timestamp)" -ForegroundColor Gray
        Write-Host "로컬 엔드포인트: $($info.local_endpoint)" -ForegroundColor Gray
        Write-Host "API 키: $($info.api_key)" -ForegroundColor Gray
    } catch {
        Write-Host "정보 파일 읽기 실패" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "파일 위치:" -ForegroundColor Yellow
Write-Host "URL 파일: $urlFile" -ForegroundColor Gray
Write-Host "정보 파일: $infoFile" -ForegroundColor Gray
Write-Host ""

# 연결 테스트
if (Test-Path $urlFile) {
    $url = Get-Content $urlFile
    Write-Host "연결 테스트 중..." -ForegroundColor Yellow
    try {
        $response = Invoke-WebRequest -Uri "$url/health" -TimeoutSec 5 -UseBasicParsing
        if ($response.StatusCode -eq 200) {
            Write-Host "연결 상태: 활성 ✓" -ForegroundColor Green
        }
    } catch {
        Write-Host "연결 상태: 실패 ✗ (터널이 중지되었을 수 있음)" -ForegroundColor Red
    }
    
    Write-Host ""
    Write-Host "사용 예시:" -ForegroundColor Yellow
    Write-Host "curl -H `"X-API-Key: Kimchi123@`" $url/api/tags" -ForegroundColor Gray
}

Write-Host ""
Write-Host "=====================================" -ForegroundColor Cyan
