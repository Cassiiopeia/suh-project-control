# SUH AI Server Health Check Script
param(
    [string]$Format = "json"
)

$healthStatus = @{
    timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    services = @{}
}

# Check Ollama
try {
    $ollamaResponse = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 5
    $healthStatus.services.ollama = @{
        status = "healthy"
        port = 11434
        models = $ollamaResponse.models.Count
    }
} catch {
    $healthStatus.services.ollama = @{
        status = "unhealthy"
        port = 11434
        error = $_.Exception.Message
    }
}

# Check Nginx
try {
    $nginxResponse = Invoke-RestMethod -Uri "http://localhost:11435/health" -Method Get -TimeoutSec 5
    $healthStatus.services.nginx = @{
        status = "healthy"
        port = 11435
    }
} catch {
    $healthStatus.services.nginx = @{
        status = "unhealthy"
        port = 11435
        error = $_.Exception.Message
    }
}

# Check Cloudflare Tunnel
$tunnelInfoPath = Join-Path $PSScriptRoot "..\data\tunnel-info.json"
if (Test-Path $tunnelInfoPath) {
    $tunnelInfo = Get-Content $tunnelInfoPath | ConvertFrom-Json
    $healthStatus.services.cloudflare = @{
        status = "configured"
        url = $tunnelInfo.tunnel.url
    }
} else {
    $healthStatus.services.cloudflare = @{
        status = "not_configured"
    }
}

# Check if cloudflared process is running
$cloudflaredProcess = Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue
if ($cloudflaredProcess) {
    $healthStatus.services.cloudflare.running = $true
} else {
    $healthStatus.services.cloudflare.running = $false
}

# Overall status
$unhealthyServices = $healthStatus.services.Values | Where-Object { $_.status -eq "unhealthy" }
$healthStatus.overall = if ($unhealthyServices.Count -eq 0) { "healthy" } else { "degraded" }

# Output based on format
if ($Format -eq "json") {
    $healthStatus | ConvertTo-Json -Depth 3
} else {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "SUH AI Server Health Check" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Timestamp: $($healthStatus.timestamp)"
    Write-Host ""
    
    foreach ($service in $healthStatus.services.Keys) {
        $status = $healthStatus.services[$service].status
        $color = if ($status -eq "healthy" -or $status -eq "configured") { "Green" } else { "Red" }
        Write-Host "$service : $status" -ForegroundColor $color
        
        if ($healthStatus.services[$service].error) {
            Write-Host "  Error: $($healthStatus.services[$service].error)" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    Write-Host "Overall Status: $($healthStatus.overall)" -ForegroundColor $(if ($healthStatus.overall -eq "healthy") { "Green" } else { "Yellow" })
}