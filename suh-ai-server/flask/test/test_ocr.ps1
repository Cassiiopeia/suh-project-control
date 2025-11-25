# Test OCR API

Write-Host "`n=== Testing Flask OCR API ===" -ForegroundColor Green

# Test 1: OCR with URL
Write-Host "`n[Test 1] OCR with image URL..." -ForegroundColor Cyan
try {
    $body = @{
        image_url = "https://www.mattmahoney.net/ocr/plaid_c150.jpg"
        prompt = "Extract all text from this image"
        model = "deepseek-ocr"
    } | ConvertTo-Json

    Write-Host "Sending request..." -ForegroundColor Yellow
    $result = Invoke-RestMethod -Uri "http://localhost:5000/ocr" `
        -Method Post `
        -ContentType "application/json" `
        -Body $body

    Write-Host "`nSuccess: $($result.success)" -ForegroundColor Green
    Write-Host "Model: $($result.model)" -ForegroundColor Yellow
    Write-Host "`nExtracted Text:" -ForegroundColor Cyan
    Write-Host $result.result -ForegroundColor White
} catch {
    Write-Host "Failed: $_" -ForegroundColor Red
    Write-Host $_.Exception.Response.StatusCode -ForegroundColor Red
}

Write-Host "`n=== Tests Completed ===" -ForegroundColor Green

