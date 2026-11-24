@echo off
:: Terminate any lingering instances to avoid pipe lockouts
taskkill /F /IM MusicalPredator.exe >nul 2>&1

:: Prefer Python runtime for immediate execution of live source code
where pythonw >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    start "" pythonw "%~dp0run_app.pyw"
    exit
)

:: Fallback to compiled standalone executable
if exist "%~dp0dist\MusicalPredator.exe" (
    start "" "%~dp0dist\MusicalPredator.exe"
    exit
)

:: Fallback to console python if pythonw is missing
where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    start "" python "%~dp0run_app.pyw"
    exit
)

echo Error: Neither Python nor dist\MusicalPredator.exe was found.
pause
exit /b 1

