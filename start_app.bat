@echo off
if exist "%~dp0dist\PredatorSync.exe" (
    start "" "%~dp0dist\PredatorSync.exe"
    exit
)
start "" pythonw "%~dp0run_app.pyw"
exit
