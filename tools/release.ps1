<#
.SYNOPSIS
  One-click release script for 5mins-tools.
.DESCRIPTION
  Switches to release branch, updates version, builds zip, pushes, verifies.
.PARAMETER Version
  Version number (e.g. 1.1.6, no 'v' prefix).
.PARAMETER NoPush
  Skip git push (local test only).
.EXAMPLE
  .\tools\release.ps1 -Version 1.1.6
  .\tools\release.ps1 -Version 1.1.6 -NoPush
#>
param(
    [Parameter(Mandatory)]
    [string]$Version,
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $Root

$Mirror1 = "http://192.168.72.219:8000/api/update/manifest"
$Mirror2 = "http://192.168.5.10:8000/api/update/manifest"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Release v$Version" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# ── 1. Switch to release ──
Write-Host "[1/5] Switching to release branch..." -ForegroundColor Yellow
git checkout release 2>&1 | Out-Null
$branch = git branch --show-current
if ($branch -ne "release") {
    Write-Host "  FAILED: cannot switch to release ($branch)" -ForegroundColor Red
    exit 1
}
# Read BUNDLE_NAME from build script (the source of truth)
$bnLine = Select-String -Path "tools/build_release.py" -Pattern 'BUNDLE_NAME\s*=' | Select-Object -First 1
$BN = ($bnLine.Line -split '"')[1]
Write-Host "  branch: $branch, bundle: $BN" -ForegroundColor Green

# ── 2. Sync main -> release ──
Write-Host "[2/5] Syncing from main..." -ForegroundColor Yellow
git fetch origin main 2>&1 | Out-Null
$behind = git rev-list --count "release..origin/main"
if ($behind -gt 0) {
    Write-Host "  main is $behind commits ahead, merging..." -ForegroundColor Yellow
    git merge "origin/main" -m "merge: sync main into release for v$Version" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  FAILED: merge conflict — resolve manually" -ForegroundColor Red
        exit 1
    }
    Write-Host "  merged" -ForegroundColor Green
} else {
    Write-Host "  already synced" -ForegroundColor Green
}

# ── 3. Build ──
Write-Host "[3/5] Building v$Version..." -ForegroundColor Yellow

$utcTime = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$releaseInfo = "{""version"":""$Version"",""name"":""$BN"",""built_at"":""$utcTime""}"
[System.IO.File]::WriteAllText("$Root\RELEASE_INFO.json", $releaseInfo, [Text.UTF8Encoding]::new($false))

$buildArgs = @("tools/build_release.py", "--version", $Version, "--mirror-url", $Mirror1)
$result = & py $buildArgs 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  FAILED: build error" -ForegroundColor Red
    Write-Host $result
    exit 1
}

# Find the built zip file
$zips = Get-ChildItem "dist" -Filter "*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$zipPath = $zips.FullName
$zipName = $zips.Name

# ── Inject backup mirror into zip's update_config.json ──
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Update)
$entry = $zip.Entries | Where-Object { $_.FullName -like "*application/portal/update_config.json" }
if ($entry) {
    $reader = New-Object System.IO.StreamReader($entry.Open())
    $config = $reader.ReadToEnd() | ConvertFrom-Json
    $reader.Close()
    $config.mirror_urls = @($Mirror1, $Mirror2)
    $config.mirror_url = $Mirror1
    $writer = New-Object System.IO.StreamWriter($entry.Open())
    $json = ($config | ConvertTo-Json -Depth 5) -replace "`r`n", "`n"
    $writer.BaseStream.SetLength(0)
    $writer.Write($json)
    $writer.Close()
}
$zip.Dispose()

$sizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
Write-Host "  Built: $zipName ($sizeMB MB)" -ForegroundColor Green

# ── 4. Commit + push ──
Write-Host "[4/5] Committing and pushing..." -ForegroundColor Yellow
git add RELEASE_INFO.json
git commit -m "chore: release v$Version" 2>&1 | Out-Null

if (-not $NoPush) {
    git push origin release 2>&1 | Out-Null
    Write-Host "  pushed release" -ForegroundColor Green
    git checkout main 2>&1 | Out-Null
    git merge release -m "merge: sync release v$Version back to main" 2>&1 | Out-Null
    git push origin main 2>&1 | Out-Null
    Write-Host "  synced main" -ForegroundColor Green
} else {
    Write-Host "  skipped push (--NoPush)" -ForegroundColor Yellow
}

# ── 5. Verify ──
Write-Host "[5/5] Verifying..." -ForegroundColor Yellow
py tools/_verify_zip.py $zipPath $Version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  FAILED: verification error" -ForegroundColor Red
    exit 1
}
Write-Host "  all checks passed" -ForegroundColor Green

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  DONE: dist/$zipName" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
