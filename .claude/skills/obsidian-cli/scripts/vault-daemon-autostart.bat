@echo off
REM ---------------------------------------------------------------------------
REM vault-daemon-autostart.bat - what Windows runs at login.
REM
REM This is the file the Startup shortcut points at. Do not add logic here: it
REM all lives in vault-daemon-autostart.ps1 beside it, which refuses when no
REM vault is configured, refuses when a daemon already holds the singleton
REM lock, rotates the log, and starts the daemon hidden.
REM
REM Install and remove the Startup shortcut with the PowerShell script itself:
REM
REM     powershell -ExecutionPolicy Bypass -File vault-daemon-autostart.ps1 -Install
REM     powershell -ExecutionPolicy Bypass -File vault-daemon-autostart.ps1 -Status
REM     powershell -ExecutionPolicy Bypass -File vault-daemon-autostart.ps1 -Uninstall
REM
REM No -NoExit here, unlike run-drill.bat: at login there is nobody to read a
REM window, so this one starts the daemon and closes. What the daemon prints
REM goes to %USERPROFILE%\.claude\vault-daemon.log; -Status shows its tail.
REM ---------------------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0vault-daemon-autostart.ps1" %*
