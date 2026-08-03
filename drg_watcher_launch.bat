@echo off
rem ============================================================
rem  Launcher: starts the watcher (watcher.py) hidden and then
rem  the game. Goes in Steam's LAUNCH OPTIONS exactly like this:
rem
rem      "C:\...\Papaio-Stats\drg_watcher_launch.bat" %command%
rem
rem  %~dp0 = this .bat's folder (finds watcher.py next to it).
rem  %*    = everything Steam passed (= %command% = the game).
rem ============================================================

rem 1) start the watcher hidden, without blocking this .bat (start = detaches)
start "" /min pythonw "%~dp0watcher.py"

rem 2) launch the game and HOLD while it runs (Steam expects this)
%*
