@echo off
setlocal

:: Install Dependencies for SUH AI Server
echo ========================================
echo Installing SUH AI Server Dependencies
echo ========================================
echo.

:: Check if running as administrator
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo This script requires administrator privileges.
    echo Please run as administrator.
    pause
    exit /b 1
)

:: Check if Chocolatey is installed
where choco >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Chocolatey is not installed. Installing Chocolatey...
    @"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -InputFormat None -ExecutionPolicy Bypass -Command "[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))" && SET "PATH=%PATH%;%ALLUSERSPROFILE%\chocolatey\bin"
    
    :: Verify installation
    where choco >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo Failed to install Chocolatey.
        pause
        exit /b 1
    )
    echo Chocolatey installed successfully.
) else (
    echo Chocolatey is already installed.
)

echo.
echo Installing required packages...
echo.

:: Install Nginx
echo Installing Nginx...
choco install nginx -y
if %ERRORLEVEL% neq 0 (
    echo Warning: Failed to install Nginx via Chocolatey.
    echo You may need to install it manually.
) else (
    echo Nginx installed successfully.
)

:: Install Ollama
echo.
echo Installing Ollama...
choco install ollama -y
if %ERRORLEVEL% neq 0 (
    echo Warning: Failed to install Ollama via Chocolatey.
    echo Please download from: https://ollama.ai/download
) else (
    echo Ollama installed successfully.
)

:: Install Cloudflared
echo.
echo Installing Cloudflared...
choco install cloudflared -y
if %ERRORLEVEL% neq 0 (
    echo Warning: Failed to install Cloudflared via Chocolatey.
    echo Please download from: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/
) else (
    echo Cloudflared installed successfully.
)

:: Install curl (for testing)
echo.
echo Installing curl...
choco install curl -y
if %ERRORLEVEL% neq 0 (
    echo Warning: Failed to install curl.
) else (
    echo Curl installed successfully.
)

echo.
echo ========================================
echo Installation Complete!
echo ========================================
echo.
echo Next steps:
echo 1. Configure Cloudflare tunnel credentials in config\credentials.json
echo 2. Update config\cloudflare-tunnel.yml with your domain
echo 3. Generate API keys using: powershell .\api\generate-api-key.ps1
echo 4. Run .\scripts\setup-windows-startup.bat to enable auto-start
echo 5. Start services using: .\scripts\start-up-auto.bat
echo.
pause

endlocal
exit /b 0