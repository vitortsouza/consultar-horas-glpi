@echo off
setlocal
wsl.exe --cd "%~dp0" -- bash run.sh he %*
set "EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %EXIT_CODE%
