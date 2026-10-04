@echo off
setlocal

set "ROOT=%~dp0"
set "ACTION=%~1"

if "%ACTION%"=="" set "ACTION=build"

docker compose -f "%ROOT%.ci\module-build\compose.yml" run --rm builder %ACTION%
exit /b %ERRORLEVEL%
