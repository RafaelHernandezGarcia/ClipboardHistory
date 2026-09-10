@echo off
:: Development launcher (Windows). Uses the project venv if it exists,
:: otherwise whatever "python" is on PATH. Console stays open for logs;
:: run_hidden.bat starts it without a console.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else (
    echo No .venv found - run:  python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    python main.py
)
