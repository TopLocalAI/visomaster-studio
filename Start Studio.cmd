@echo off
cd /d "%~dp0"
if exist "dependencies\Python\pythonw.exe" (
  start "" "dependencies\Python\pythonw.exe" "studio.py"
  exit /b
)
if exist ".venv-studio\Scripts\pythonw.exe" (
  start "" ".venv-studio\Scripts\pythonw.exe" "studio.py"
  exit /b
)
echo Please use the complete VisoMaster Studio package.
pause
