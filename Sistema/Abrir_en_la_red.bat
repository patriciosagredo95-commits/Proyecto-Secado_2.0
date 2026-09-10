@echo off
rem Permite que otros equipos de la planta entren al sistema.
rem Hay que ejecutarlo UNA VEZ, con boton derecho > "Ejecutar como administrador".
title Abrir el sistema de secado a la red
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Este archivo necesita permisos de administrador.
  echo   Cierra esta ventana, haz clic derecho sobre Abrir_en_la_red.bat
  echo   y elige "Ejecutar como administrador".
  echo.
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="Sistema de Secado Glover" >nul 2>&1
netsh advfirewall firewall add rule name="Sistema de Secado Glover" dir=in action=allow protocol=TCP localport=8765 profile=domain,private
echo.
echo   Listo. El puerto 8765 quedo abierto para la red local.
echo.
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo   Direccion:  http://%%a:8765
echo.
pause
