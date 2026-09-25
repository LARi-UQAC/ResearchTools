@echo off
REM ---------------------------------------------------------------------------
REM  aider-night.bat - start a night of coding on one project.
REM
REM  Usage:   aider-night.bat <project-path> [extra aider-night.ps1 switches]
REM  Example: aider-night.bat C:\work\my-project
REM           aider-night.bat C:\work\my-project -DryRun
REM           aider-night.bat C:\work\my-project -PullRequest
REM
REM  The skills are already wired: nothing else is typed. -NoSkills turns them
REM  off, which is how one night is compared against another.
REM
REM  Two things this file exists to get right:
REM
REM  1. -ExecutionPolicy Bypass applies to THIS PROCESS ONLY. It never changes
REM     the machine's policy, which is not a decision a coding script may take.
REM
REM  2. The exit code is the driver's, propagated. Any command placed after the
REM     PowerShell call would overwrite ERRORLEVEL and a failed night would then
REM     read as a success - a mistake already made once in a test harness here.
REM ---------------------------------------------------------------------------

if "%~1"=="" (
    echo Usage: %~nx0 ^<project-path^> [switches]
    echo.
    echo   -DryRun        print what would happen, start no model, write nothing
    echo   -NoSkills      run without the per-stage skills
    echo   -Branch NAME   work on NAME instead of night-YYYY-MM-DD
    echo   -Push          push the branch when every plan is done
    echo   -PullRequest   push, then open a pull request. Never merges.
    exit /b 2
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0aider-night.ps1" -Project %*
exit /b %ERRORLEVEL%
