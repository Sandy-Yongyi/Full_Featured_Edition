@echo off
cd /d "%~dp0"
py -3.11 tools\release_sdk.py %*
if errorlevel 1 (
    echo Release failed. Review the error above.
    pause
    exit /b 1
)
echo Release completed. Send only the ZIP shown above.
pause
