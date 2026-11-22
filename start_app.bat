@echo off
if exist "%~dp0dist\MusicalPredator.exe" (
    start "" "%~dp0dist\MusicalPredator.exe"
    exit
)
start "" pythonw "%~dp0run_app.pyw"
exit
