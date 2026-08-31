@echo off
rem Start the rt-observe dashboard. Thin wrapper, no logic.
rem
rem The double-click entry, the same shape run-drill.bat already uses beside
rem run-drill.ps1. It forwards every argument to the PowerShell wrapper in this
rem directory, which forwards them to the canonical launcher beside its module.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0rt-dashboard.ps1" %*
exit /b %ERRORLEVEL%
