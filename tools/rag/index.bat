@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Resolve project root
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"

set "PYTHON=%ROOT%\.tmp\cache\rag-venv\Scripts\python.exe"
set "INDEXER=%ROOT%\tools\rag\index.py"

if not exist "%PYTHON%" goto missing_python
if not exist "%INDEXER%" goto missing_indexer

echo.
echo ======================================
echo        SkyFire RAG Indexer
echo ======================================
echo.
echo 1. Full indexing / incremental update
echo 2. Test indexing - 20 changed files
echo 3. Exit
echo.

choice /c 123 /n /m "Select an option: "

if errorlevel 3 goto end
if errorlevel 2 goto test
if errorlevel 1 goto full

:full
echo.
echo [INFO] Starting incremental indexing...
"%PYTHON%" "%INDEXER%"
goto finish

:test
echo.
echo [INFO] Indexing 20 changed files...
"%PYTHON%" "%INDEXER%" --limit-files 20
goto finish

:finish
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" goto failed

echo [OK] Indexing completed.
goto done

:failed
echo [ERROR] Indexing failed. Exit code: %RESULT%
goto done

:missing_python
echo [ERROR] Python environment not found.
echo "%PYTHON%"
goto done

:missing_indexer
echo [ERROR] Indexer not found.
echo "%INDEXER%"
goto done

:done
echo.
pause
exit /b %RESULT%

:end
exit /b 0
