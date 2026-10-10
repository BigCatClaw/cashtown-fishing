@echo off
title Cash Town Fishing Log
cd /d "%~dp0"
python server.py
if errorlevel 1 pause
