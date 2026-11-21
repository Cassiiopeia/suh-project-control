@echo off
rem gbrain-http NSSM launcher: admin token file > GBRAIN_ADMIN_BOOTSTRAP_TOKEN > gbrain serve --http (127.0.0.1 only)
rem Source of truth: repo suh-ai-server/scripts/gbrain/run-gbrain-http.cmd, copied to C:\AI\gbrain by setup-gbrain-http.ps1
rem All values come from NSSM AppEnvironmentExtra written by setup-gbrain-http.ps1 (token never stored in the registry)
setlocal
if not exist "%GBRAIN_ADMIN_TOKEN_FILE%" (
  echo [gbrain-http] admin token file missing: %GBRAIN_ADMIN_TOKEN_FILE%
  exit /b 1
)
set /p GBRAIN_ADMIN_BOOTSTRAP_TOKEN=<"%GBRAIN_ADMIN_TOKEN_FILE%"
"%GBRAIN_BUN_EXE%" "%GBRAIN_CLI_PATH%" serve --http --port %GBRAIN_PORT% --bind 127.0.0.1 --surface starter --advertise verbs --suppress-bootstrap-token
