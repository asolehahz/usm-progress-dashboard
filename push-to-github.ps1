# Push USM Streamlit app to a new public GitHub repo (Streamlit-only, no Django).
# Run in PowerShell from this folder:  .\push-to-github.ps1

$ErrorActionPreference = "Stop"
$git = "C:\Program Files\Git\bin\git.exe"
$gh  = "C:\Program Files\GitHub CLI\gh.exe"

Set-Location $PSScriptRoot

Write-Host "=== Step 1: GitHub login ===" -ForegroundColor Cyan
& $gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Opening GitHub login (follow the browser prompts)..."
    & $gh auth login -h github.com -p https -w
}

Write-Host "`n=== Step 2: Create public repo and push ===" -ForegroundColor Cyan
$repoName = Read-Host "GitHub repo name (e.g. usm-progress-dashboard)"
if (-not $repoName) { $repoName = "usm-progress-dashboard" }

& $gh repo create $repoName --public --source=. --remote=origin --push --description "USM campus progress dashboard (Streamlit + Google Sheets)"

if ($LASTEXITCODE -eq 0) {
    $url = & $gh repo view --json url -q .url
    Write-Host "`nDone! Public repo:" -ForegroundColor Green
    Write-Host $url
    Write-Host "`nNext: deploy at https://share.streamlit.io — main file: app.py"
} else {
    Write-Host "`nIf the repo already exists, run:" -ForegroundColor Yellow
    Write-Host "  & `"$git`" remote add origin https://github.com/YOUR_USERNAME/$repoName.git"
    Write-Host "  & `"$git`" push -u origin main"
}
