# Ollama-OCR.ps1
# URL 또는 로컬 이미지로 OCR 수행

param(
    [Parameter(Mandatory=$true)]
    [string]$ImageSource,
    
    [Parameter(Mandatory=$false)]
    [string]$Prompt = "Extract all text from this image",
    
    [Parameter(Mandatory=$false)]
    [string]$Model = "deepseek-ocr",
    
    [Parameter(Mandatory=$false)]
    [string]$OllamaUrl = "http://localhost:11434"
)

function Get-ImageBase64 {
    param(
        [string]$Source
    )
    
    $tempFile = $null
    
    try {
        # URL인지 로컬 파일인지 확인
        if ($Source -match "^https?://") {
            Write-Host "🌐 Downloading image from URL..." -ForegroundColor Cyan
            $tempFile = "$env:TEMP\ollama_$(Get-Random).jpg"
            Invoke-WebRequest -Uri $Source -OutFile $tempFile -ErrorAction Stop
            $imagePath = $tempFile
        }
        elseif (Test-Path $Source) {
            Write-Host "📁 Reading local image..." -ForegroundColor Cyan
            $imagePath = $Source
        }
        else {
            throw "Image source not found: $Source"
        }
        
        # Base64 인코딩
        Write-Host "🔄 Encoding to base64..." -ForegroundColor Cyan
        $base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($imagePath))
        
        return $base64
    }
    finally {
        # 임시 파일 정리
        if ($tempFile -and (Test-Path $tempFile)) {
            Remove-Item $tempFile -Force
        }
    }
}

function Invoke-OllamaOCR {
    param(
        [string]$Base64Image,
        [string]$Prompt,
        [string]$Model,
        [string]$ApiUrl
    )
    
    Write-Host "🤖 Sending to Ollama ($Model)..." -ForegroundColor Cyan
    
    # API 요청 본문 구성
    $body = @{
        model = $Model
        messages = @(
            @{
                role = "user"
                content = $Prompt
                images = @($Base64Image)
            }
        )
        stream = $false
    } | ConvertTo-Json -Depth 10
    
    try {
        # API 호출
        $response = Invoke-RestMethod `
            -Uri "$ApiUrl/api/chat" `
            -Method Post `
            -Body $body `
            -ContentType "application/json" `
            -ErrorAction Stop
        
        return $response.message.content
    }
    catch {
        Write-Host "❌ Error calling Ollama API: $_" -ForegroundColor Red
        throw
    }
}

# 메인 실행
try {
    Write-Host "`n=== Ollama OCR ===" -ForegroundColor Green
    Write-Host "Image: $ImageSource" -ForegroundColor Yellow
    Write-Host "Model: $Model" -ForegroundColor Yellow
    Write-Host "Prompt: $Prompt`n" -ForegroundColor Yellow
    
    # 이미지를 base64로 변환
    $base64Image = Get-ImageBase64 -Source $ImageSource
    
    # Ollama OCR 실행
    $result = Invoke-OllamaOCR `
        -Base64Image $base64Image `
        -Prompt $Prompt `
        -Model $Model `
        -ApiUrl $OllamaUrl
    
    # 결과 출력
    Write-Host "`n=== Result ===" -ForegroundColor Green
    Write-Host $result -ForegroundColor White
    Write-Host "`n✅ Completed!`n" -ForegroundColor Green
}
catch {
    Write-Host "`n❌ Error: $_`n" -ForegroundColor Red
    exit 1
}