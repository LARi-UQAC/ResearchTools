@echo off
REM litellm-autostart.bat - what Windows runs at login for the LiteLLM proxy (Issue #112).
REM All logic lives in litellm-autostart.ps1 beside it. Install or remove the Startup
REM shortcut with: powershell -NoProfile -ExecutionPolicy Bypass -File litellm-autostart.ps1 -Install
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0litellm-autostart.ps1" %*
