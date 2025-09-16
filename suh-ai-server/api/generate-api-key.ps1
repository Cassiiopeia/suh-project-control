# API Key Generator for SUH AI Server
param(
    [Parameter(Mandatory=$false)]
    [string]$Name = "default",
    
    [Parameter(Mandatory=$false)]
    [string]$Type = "api_key" # api_key or bearer_token
)

$configDir = Join-Path $PSScriptRoot "..\config"
if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}

# Generate a secure random key
function Generate-SecureKey {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RNGCryptoServiceProvider]::Create().GetBytes($bytes)
    $key = [System.Convert]::ToBase64String($bytes)
    return $key -replace '[/+=]', '' # Remove special characters for URL safety
}

$key = Generate-SecureKey
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# Determine file based on type
$fileName = if ($Type -eq "bearer_token") { "auth_tokens.txt" } else { "api_keys.txt" }
$filePath = Join-Path $configDir $fileName

# Create file if it doesn't exist
if (-not (Test-Path $filePath)) {
    New-Item -ItemType File -Path $filePath -Force | Out-Null
}

# Add key to file with metadata (stored separately)
Add-Content -Path $filePath -Value $key

# Store metadata
$metadataFile = Join-Path $configDir "keys_metadata.json"
$metadata = @{
    key_prefix = $key.Substring(0, 8)
    name = $Name
    type = $Type
    created = $timestamp
    active = $true
}

# Load existing metadata
$allMetadata = @()
if (Test-Path $metadataFile) {
    $allMetadata = Get-Content $metadataFile | ConvertFrom-Json
}

# Add new metadata
$allMetadata += $metadata

# Save metadata
$allMetadata | ConvertTo-Json -Depth 3 | Set-Content $metadataFile

# Output
Write-Host "========================================" -ForegroundColor Green
Write-Host "API Key Generated Successfully" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Name: $Name"
Write-Host "Type: $Type"
Write-Host "Created: $timestamp"
Write-Host ""
Write-Host "Key: $key" -ForegroundColor Yellow
Write-Host ""
Write-Host "IMPORTANT: Save this key securely. It won't be shown again." -ForegroundColor Red
Write-Host ""
Write-Host "Usage:" -ForegroundColor Cyan
if ($Type -eq "bearer_token") {
    Write-Host "  Authorization: Bearer $key"
} else {
    Write-Host "  X-API-KEY: $key"
}
Write-Host ""
Write-Host "The key has been added to: $filePath"