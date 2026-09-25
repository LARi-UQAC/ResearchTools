@echo off
REM ---------------------------------------------------------------------------
REM ollama-tune.bat - double-click entry point for the Ollama tuning test.
REM
REM Measures this machine and prints how to configure Ollama for it, then writes
REM the numbers into CONFIG_OLLAMA.md. Read that file for what they mean.
REM
REM Why a .bat at all: the night side of this kit runs with no Claude Code and
REM no shell open, and a student on a fresh machine has PowerShell's execution
REM policy in the way. This bypasses it for THIS process only, which is the
REM narrowest scope that works, rather than telling a reader to change their
REM machine's policy permanently.
REM
REM Usage:
REM   ollama-tune.bat                 the quick run, about 15 minutes
REM   ollama-tune.bat floor           the arithmetic only, seconds, no model
REM   ollama-tune.bat promptfloor     what the harness ACTUALLY sent, from the
REM                                   run logs of the project in this directory.
REM                                   No model, no GPU, seconds. Needs one run's
REM                                   logs to exist first
REM   ollama-tune.bat full            every axis, budget an hour
REM   ollama-tune.bat repeat          the careful offload sweep: every rung
REM                                   measured 3 times and interleaved, so a
REM                                   difference smaller than the machine's
REM                                   own noise is not read as a result
REM   ollama-tune.bat quick apply     quick run, and write CONFIG_OLLAMA.md
REM   ollama-tune.bat context apply   context sweep, and write the file
REM ---------------------------------------------------------------------------
setlocal

set "PHASE=%~1"
if "%PHASE%"=="" set "PHASE=quick"

set "APPLY="
if /i "%~2"=="apply" set "APPLY=-Apply"
if /i "%~2"=="-apply" set "APPLY=-Apply"

set "SCRIPT=%~dp0ollama-tune.ps1"
if not exist "%SCRIPT%" (
    echo REFUSED: ollama-tune.ps1 was not found beside this file.
    echo   Expected: "%SCRIPT%"
    echo   The .bat is only a launcher; it holds no logic of its own.
    exit /b 2
)

REM PowerShell is located rather than assumed: pwsh first when present, then the
REM Windows-shipped powershell.exe. Naming every candidate on failure is what
REM makes a missing interpreter diagnosable instead of a silent nothing.
set "PS="
where pwsh.exe >nul 2>nul && set "PS=pwsh.exe"
if not defined PS where powershell.exe >nul 2>nul && set "PS=powershell.exe"
if not defined PS (
    echo REFUSED: no PowerShell found on PATH.
    echo   Tried: pwsh.exe, powershell.exe
    exit /b 2
)

echo Running the Ollama tuning test: phase "%PHASE%"
echo.
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -Phase "%PHASE%" %APPLY%
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo Done. Read CONFIG_OLLAMA.md for what these numbers mean.
) else (
    echo The test exited with code %RC%. Nothing was applied to Ollama.
)

REM Keep the window open when double-clicked, so the result is readable. A
REM student who launched this from Explorer would otherwise see it vanish.
if not defined PROMPT_IS_INTERACTIVE pause >nul 2>nul
exit /b %RC%
