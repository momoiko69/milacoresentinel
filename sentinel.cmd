@echo off
REM Sentinel ENCORE Epistemic Auditor CLI shim
set PYTHONUTF8=1
python "%~dp0sentinel_encore_audit.py" %*

