@echo off
title Start Acer Lighting Service
echo Starting Acer Lighting Service...
sc config AcerLightingService start= auto >nul 2>&1
net start AcerLightingService
if %ERRORLEVEL% equ 0 (
    echo.
    echo Acer Lighting Service started successfully!
) else (
    echo.
    echo Failed to start service. Please ensure you right-clicked and selected "Run as administrator".
)
echo.
pause
