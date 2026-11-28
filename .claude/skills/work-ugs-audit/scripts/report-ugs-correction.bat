@echo off
rem report-ugs-correction - grade a folder of student reports with one command (owner, 2026-11-28).
rem Usage: report-ugs-correction "<reports folder>" [--work <folder>] [--type <type>] [--rubric <file>] [--ignore-gpu] [--dry-run]
rem Run the same line again after a crash or a reboot: the grading resumes where it stopped.
rem No logic here: it finds the interpreter and calls "ugs_driver.py auto". Exit codes are those of the driver.
setlocal
if "%~1"=="" goto usage
set "SCRIPTS=%~dp0"
set "PYTHONIOENCODING=utf-8"
rem The interpreter of this clone, else of the main clone of a worktree (R37: never the first python on PATH).
set "PY=%SCRIPTS%..\..\..\..\.venv-skills\Scripts\python.exe"
if exist "%PY%" goto run
set "COMMON="
for /f "delims=" %%i in ('git -C "%SCRIPTS%." rev-parse --path-format^=absolute --git-common-dir 2^>nul') do set "COMMON=%%i"
if not defined COMMON goto nopython
set "PY=%COMMON%\..\.venv-skills\Scripts\python.exe"
if exist "%PY%" goto run
:nopython
echo No interpreter found: looked for .venv-skills in this clone and in its main clone.
echo Build it with: setup.ps1 -InstallPython
exit /b 2
:run
"%PY%" "%SCRIPTS%ugs_driver.py" auto --reports %*
exit /b %ERRORLEVEL%
:usage
echo Usage: report-ugs-correction "^<reports folder^>" [--work ^<folder^>] [--type ^<type^>] [--rubric ^<file^>] [--ignore-gpu] [--dry-run]
exit /b 2
