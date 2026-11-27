@echo off
rem Instalador do J' PZ MAP STUDIO para Windows: duplo clique aqui.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo. & echo A instalacao falhou (codigo %RC%). Veja a mensagem acima.
echo.
pause
exit /b %RC%
