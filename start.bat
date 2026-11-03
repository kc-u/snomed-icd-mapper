@echo off
rem Start the mapper at http://localhost:8765
rem Live I-MAGIC queries use the Python in PYTHON; a local .venv is picked up automatically.
cd /d "%~dp0"
if "%PYTHON%"=="" if exist ".venv\Scripts\python.exe" set PYTHON=%CD%\.venv\Scripts\python.exe
if "%PYTHON%"=="" set PYTHON=python
node server.js
