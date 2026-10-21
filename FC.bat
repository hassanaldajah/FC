@echo off
rem Runs FC from its own environment (.venv); falls back to the system Python.
if exist "%~dp0.venv\Scripts\pythonw.exe" (start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0fc.py") else (start "" pyw "%~dp0fc.py")
