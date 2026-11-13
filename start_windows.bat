@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON=py -3"
) else (
  set "PYTHON=python"
)
%PYTHON% -c "import PIL; import tkinter" >nul 2>nul
if errorlevel 1 (
  echo Python with Tkinter and Pillow is required.
  echo Installing Pillow into the current Python environment...
  %PYTHON% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Installation failed. Install Python 3.9+ and run: py -3 -m pip install pillow
    pause
    exit /b 1
  )
)
%PYTHON% -m inti_explorer
if errorlevel 1 (
  echo.
  echo GUI exited with an error.
  pause
)
