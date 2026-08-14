@echo off
setlocal EnableDelayedExpansion
REM ============================================================================
REM CIE-OS / A01 Blockchain Intelligence Agent
REM
REM Double-clickable runner: resolve the interpreter, capture recent blocks,
REM and report what A01 now holds.
REM
REM Two things this script exists to prevent, both of which have already
REM happened during development:
REM
REM   1. Running the wrong Python. The system interpreter lacks
REM      pydantic-settings and aiosqlite, so `doctor` fails and three test
REM      modules will not even import. The failure looks like a broken agent
REM      rather than a wrong PATH, so this resolves the interpreter explicitly
REM      and refuses to guess.
REM
REM   2. A window that closes before the error can be read. Every exit path
REM      pauses, because a double-clicked console that vanishes leaves an
REM      operator with nothing at all.
REM
REM Paths are derived from this script's own location. Nothing is hardcoded:
REM the repository sits under a directory whose name contains spaces and an
REM unbalanced parenthesis, so every path is quoted.
REM ============================================================================

title A01 Blockchain Intelligence

set "SCRIPT_DIR=%~dp0"
set "AGENT_DIR=%SCRIPT_DIR%.."
pushd "%AGENT_DIR%" || (echo Cannot enter the agent directory. & pause & exit /b 1)
set "AGENT_DIR=%CD%"

echo.
echo ============================================================
echo   A01 Blockchain Intelligence
echo ============================================================
echo   agent : %AGENT_DIR%

REM -- Locate an interpreter ---------------------------------------------------
REM Preference order: an explicit override, a venv beside or above the agent,
REM then PATH as a last resort with a warning.
set "PYTHON="

if defined A01_PYTHON (
    if exist "%A01_PYTHON%" set "PYTHON=%A01_PYTHON%"
)

if not defined PYTHON (
    for %%D in ("%AGENT_DIR%" "%AGENT_DIR%\.." "%AGENT_DIR%\..\.." "%AGENT_DIR%\..\..\..") do (
        if not defined PYTHON (
            if exist "%%~fD\.venv\Scripts\python.exe" set "PYTHON=%%~fD\.venv\Scripts\python.exe"
        )
    )
)

REM A venv is not always an ancestor of the agent. This checkout's interpreter
REM lives in an entirely separate tree, so an upward search cannot reach it --
REM and falling through to the system Python looks like a broken agent rather
REM than a misconfigured path. `A01_PYTHON` in a .env file fixes that with the
REM same file that already holds the provider keys.
if not defined PYTHON (
    for %%D in ("%AGENT_DIR%" "%AGENT_DIR%\.." "%AGENT_DIR%\..\.." "%AGENT_DIR%\..\..\..") do (
        for %%F in (".env.local" ".env") do (
            if not defined PYTHON (
                if exist "%%~fD\%%~F" (
                    for /f "usebackq tokens=1,* delims==" %%K in ("%%~fD\%%~F") do (
                        if /i "%%~K"=="A01_PYTHON" (
                            if not defined PYTHON (
                                set "CANDIDATE=%%~L"
                                REM Strip surrounding quotes the file may carry.
                                set "CANDIDATE=!CANDIDATE:"=!"
                                if exist "!CANDIDATE!" set "PYTHON=!CANDIDATE!"
                            )
                        )
                    )
                )
            )
        )
    )
)

if not defined PYTHON (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "delims=" %%P in ('where python') do (
            if not defined PYTHON set "PYTHON=%%P"
        )
        echo.
        echo   WARNING: no virtualenv found; falling back to Python on PATH.
        echo            If doctor reports a settings failure, that is why:
        echo            the system interpreter is missing pydantic-settings.
    )
)

if not defined PYTHON (
    echo.
    echo   ERROR: no Python interpreter found.
    echo.
    echo   Looked for a .venv beside the agent and up to three levels above it,
    echo   then for python on PATH. Set A01_PYTHON to an interpreter to override:
    echo.
    echo       set A01_PYTHON=C:\path\to\python.exe
    echo.
    popd & pause & exit /b 1
)

echo   python: %PYTHON%
echo.

REM -- Settings ----------------------------------------------------------------
if "%A01_DB%"=="" set "A01_DB=%AGENT_DIR%\data\a01.db"
if "%A01_CHAIN%"=="" set "A01_CHAIN=ethereum"
if "%A01_BLOCKS%"=="" set "A01_BLOCKS=25"

if not exist "%AGENT_DIR%\data" mkdir "%AGENT_DIR%\data"

echo   chain : %A01_CHAIN%    blocks: %A01_BLOCKS%
echo   db    : %A01_DB%
echo.
echo ------------------------------------------------------------
echo   1/3  Self-check
echo ------------------------------------------------------------
"%PYTHON%" -m cli doctor
if errorlevel 1 (
    echo.
    echo   Doctor reported a problem. Ingestion is skipped: capturing into a
    echo   system that fails its own checks would store data nobody should
    echo   trust.
    popd & pause & exit /b 1
)

echo.
echo ------------------------------------------------------------
echo   2/3  Capture
echo ------------------------------------------------------------
"%PYTHON%" -m cli ingest --db "%A01_DB%" --chain "%A01_CHAIN%" --blocks %A01_BLOCKS% --tokens
set "INGEST_RC=%errorlevel%"
if not "%INGEST_RC%"=="0" (
    echo.
    echo   Capture finished with exit code %INGEST_RC%.
    echo   Code 2 means some records were refused; the rest were stored.
)

echo.
echo ------------------------------------------------------------
echo   3/3  Status
echo ------------------------------------------------------------
"%PYTHON%" -m cli metrics --db "%A01_DB%"

echo.
echo ============================================================
echo   Done.
echo.
echo   Investigate an address:
echo     "%PYTHON%" -m cli investigate --db "%A01_DB%" --address 0x...
echo.
echo   Serve the read-only API on 127.0.0.1:8801:
echo     "%PYTHON%" -m cli serve --db "%A01_DB%"
echo.
echo   Run this automatically every 10 minutes:
echo     powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install-task.ps1"
echo ============================================================
echo.

popd
pause
endlocal
