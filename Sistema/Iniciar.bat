@echo off
rem Sistema de secado Glover - arranque local
title Sistema de Secado Glover
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo   No se encontro Python en este equipo.
  echo   Instala Python 3.10 o superior desde python.org marcando
  echo   "Add python.exe to PATH" y vuelve a ejecutar este archivo.
  echo.
  pause
  exit /b 1
)

echo.
echo   Iniciando el sistema de secado...
echo   El navegador se abrira solo. Cierra esta ventana para detenerlo.
echo.
python servidor.py %1
pause
