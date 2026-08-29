@echo off
REM ---------------------------------------------------------------------------
REM run-drill.bat - double-click entry point for the vault daemon's e2e drill.
REM
REM Everything of substance is in run-drill.ps1 beside this file. This wrapper
REM exists only so the drill can be started without typing a PowerShell command
REM line, and it passes its arguments straight through:
REM
REM     run-drill.bat                       the whole thing, phases 0 to 6
REM     run-drill.bat -SkipTests            skip the offline suite
REM     run-drill.bat -Only filed,parked    one or two steps
REM     run-drill.bat -Yes                  do not prompt before the teardown
REM     run-drill.bat -KeepVaultChanges     leave the drill's notes in the vault
REM
REM It opens a SECOND window for the daemon and closes it at the end. The drill
REM itself runs in this window, so read this one for the result.
REM
REM -NoExit keeps this window open after the run so the final JSON and the
REM teardown report can be read; a double-clicked window would otherwise vanish
REM with the answer in it.
REM ---------------------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0run-drill.ps1" %*
