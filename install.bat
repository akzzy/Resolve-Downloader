@echo off
title Installing Resolve Downloader...
echo =======================================================
echo              RESOLVE DOWNLOADER INSTALLER
echo =======================================================
echo.

:: 1. Check Python installation
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found on your system!
    echo Please download and install Python from python.org
    echo and ensure "Add Python to PATH" is checked during setup.
    echo.
    pause
    exit /b 1
)

:: 2. Install dependencies
echo [1/3] Checking and installing dependencies...
python -m pip install --upgrade pip
python -m pip install yt-dlp
if %errorlevel% neq 0 (
    echo [WARNING] Failed to install yt-dlp dependencies via standard pip.
    echo Trying user-scoped pip installation...
    python -m pip install --user yt-dlp
)

:: 3. Run script installer
echo.
echo [2/3] Installing Workflow Integration into DaVinci Resolve...
python "%~dp0resolve_downloader.py" --install
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Installation failed!
    echo.
    pause
    exit /b 1
)

:: 4. Verify native node fallback
echo [3/3] Checking native registration assets...
if exist "%~dp0WorkflowIntegration.node" (
    echo Copying local fallback native node binary...
    copy /Y "%~dp0WorkflowIntegration.node" "%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Workflow Integration Plugins\com.antigravity.resolve.downloader\WorkflowIntegration.node" >nul
)

echo.
echo =======================================================
echo          INSTALLATION COMPLETED SUCCESSFULLY!
echo =======================================================
echo.
echo Next Steps:
echo 1. Restart DaVinci Resolve Studio.
echo 2. Open the panel by navigating to:
echo    Workspace -^> Workflow Integrations -^> Resolve Video Downloader
echo.
pause
