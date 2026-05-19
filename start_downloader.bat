@echo off
title Resolve Video Downloader Launcher
echo Starting background downloader server...
start /b python resolve_downloader.py --server --port 8554
echo Waiting for server to initialize...
timeout /t 2 /nobreak >nul
echo Launching premium interface in your default web browser...
start http://localhost:8554
echo.
echo ==========================================================
echo  RESOLVE DOWNLOADER RUNNING
echo ==========================================================
echo  You can now fetch and download clips inside your browser.
echo  Downloaded files will import into DaVinci Resolve.
echo.
echo  Keep this window open while using the downloader.
echo  Press Ctrl+C inside this window to close the server.
echo ==========================================================
echo.
pause
