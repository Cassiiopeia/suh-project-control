@echo off
setlocal

:: Setup Windows Startup for SUH AI Server
echo ========================================
echo Setting up Windows Startup
echo ========================================
echo.

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SCRIPT_PATH=%~dp0start-up-auto.bat"
set "SHORTCUT_NAME=SUH AI Server.lnk"

:: Create VBScript to create shortcut
echo Creating startup shortcut...
(
    echo Set objShell = CreateObject^("WScript.Shell"^)
    echo strStartupFolder = objShell.SpecialFolders^("Startup"^)
    echo Set objShortcut = objShell.CreateShortcut^(strStartupFolder ^& "\%SHORTCUT_NAME%"^)
    echo objShortcut.TargetPath = "%SCRIPT_PATH%"
    echo objShortcut.WorkingDirectory = "%~dp0.."
    echo objShortcut.WindowStyle = 1
    echo objShortcut.Description = "SUH AI Server Auto Startup"
    echo objShortcut.Save
) > "%TEMP%\create_shortcut.vbs"

:: Execute VBScript
cscript //nologo "%TEMP%\create_shortcut.vbs"

:: Clean up
del "%TEMP%\create_shortcut.vbs"

echo.
echo Startup shortcut created successfully!
echo SUH AI Server will now start automatically when Windows starts.
echo.
echo To remove from startup, delete: 
echo "%STARTUP_DIR%\%SHORTCUT_NAME%"
echo.
pause

endlocal
exit /b 0