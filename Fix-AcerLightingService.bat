@echo off
setlocal EnableDelayedExpansion
title Fix and Recover Acer Lighting Service
color 0b

echo ======================================================================
echo          MUSICALPREDATOR - ACER LIGHTING SERVICE RECOVERY
echo ======================================================================
echo.

:: Check for Administrator elevation
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [REQUESTING ELEVATION] Administrator permissions required.
    echo Prompting for administrator access...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo [*] Administrator privileges confirmed.
echo.

echo [1/4] Terminating any crashed or hanging service instances...
taskkill /F /IM AcerLightingService.exe >nul 2>&1
net stop AcerLightingService >nul 2>&1
timeout /t 1 /nobreak >nul

echo [2/4] Purging corrupted LightingProfile cache (Heap Corruption 0xc0000374 fix)...
if exist "C:\ProgramData\OEM\AcerLightingService\LightingProfile\LightingProfile.ini" (
    del /F /Q "C:\ProgramData\OEM\AcerLightingService\LightingProfile\LightingProfile.ini" >nul 2>&1
    echo       [OK] Corrupted LightingProfile.ini purged successfully.
) else (
    echo       [OK] Profile directory is clean.
)

echo [3/4] Configuring Acer Lighting Service startup and crash auto-recovery...
sc config AcerLightingService start= auto >nul 2>&1
sc failure AcerLightingService reset= 60 actions= restart/1000/restart/2000/restart/5000 >nul 2>&1

echo [4/4] Starting Acer Lighting Service...
net start AcerLightingService
if %errorlevel% equ 0 (
    echo.
    echo ======================================================================
    echo  [SUCCESS] Acer Lighting Service is now RUNNING!
    echo.
    echo  Physical Keyboard Named Pipe (\\.\pipe\AcerLightingService_NamedPipe)
    echo  is active and healthy.
    echo.
    echo  MusicalPredator will now automatically connect to your real keyboard.
    echo ======================================================================
) else (
    echo.
    echo [RETRY] Attempting direct sc start...
    sc start AcerLightingService
    timeout /t 2 /nobreak >nul
    sc query AcerLightingService
)

echo.
echo Press any key to close this recovery window...
pause >nul
