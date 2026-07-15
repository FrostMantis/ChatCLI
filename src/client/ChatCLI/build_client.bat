@echo off
set ELECTRON_ENABLE_LOGGING=true
set ELECTRON_DISABLE_SECURITY_WARNINGS=true
rem Install dependencies (if you need to)
call npm install

rem Make the distributable
call npm run build:win


rem Wait for a keypress before closing
pause