@echo off
rem Runs HK File from its own environment (.venv); falls back to the system Python.
if exist "%~dp0.venv\Scripts\pythonw.exe" (start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0hkfile.py") else (start "" pyw "%~dp0hkfile.py")
