@echo off
REM Push USM Streamlit app to GitHub (no PowerShell script policy needed)
setlocal
cd /d "%~dp0"

set GIT="C:\Program Files\Git\bin\git.exe"
set GH="C:\Program Files\GitHub CLI\gh.exe"

echo === Checking Git ===
%GIT% --version
if errorlevel 1 (
  echo Git not found. Install from https://git-scm.com/download/win
  pause
  exit /b 1
)

echo.
echo === Checking GitHub login ===
%GH% auth status
if errorlevel 1 (
  echo.
  echo Not logged in. A browser window will open — sign in to GitHub.
  %GH% auth login -h github.com -p https -w
)

echo.
set /p REPO_NAME=GitHub repo name [usm-progress-dashboard]: 
if "%REPO_NAME%"=="" set REPO_NAME=usm-progress-dashboard

echo.
echo Creating public repo "%REPO_NAME%" and pushing...
%GH% repo create %REPO_NAME% --public --source=. --remote=origin --push --description "USM campus progress dashboard (Streamlit + Google Sheets)"

if errorlevel 1 (
  echo.
  echo If repo already exists, add remote manually:
  echo   %GIT% remote add origin https://github.com/YOUR_USERNAME/%REPO_NAME%.git
  echo   %GIT% push -u origin main
) else (
  echo.
  echo Done! Repo URL:
  %GH% repo view --json url -q .url
  echo.
  echo Next: deploy at https://share.streamlit.io  main file: app.py
)

echo.
pause
