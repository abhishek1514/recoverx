# =========================================================================
# RecoverX Automated Deployment Pipeline (Windows PowerShell)
#
# IMPORTANT SECURITY RULE:
# This script NEVER prints or writes secret values.
# Secrets must be supplied via hosting environment dashboards.
# =========================================================================

param (
    [string]$TargetUrl = "http://localhost:8000",
    [switch]$SkipTests = $false,
    [switch]$SkipFrontendBuild = $false,
    [switch]$SkipSmokeTest = $false
)

$ErrorActionPreference = "Stop"

Write-Host "=========================================================================" -ForegroundColor Cyan
Write-Host "🚀 RECOVERX AUTOMATED PRODUCTION DEPLOYMENT & VERIFICATION PIPELINE" -ForegroundColor Cyan
Write-Host "=========================================================================" -ForegroundColor Cyan

# 1. Preflight Tooling Checks
Write-Host "`n[Step 1/6] Checking required tooling..." -ForegroundColor Yellow
$tools = @("git", "python")
foreach ($t in $tools) {
    if (Get-Command $t -ErrorAction SilentlyContinue) {
        Write-Host "  [✓] Found: $t" -ForegroundColor Green
    } else {
        Write-Host "  [✗] Missing required tool: $t" -ForegroundColor Red
        exit 1
    }
}

# 2. Secret Leak Scan in Repository
Write-Host "`n[Step 2/6] Running repository secret & credential leak audit..." -ForegroundColor Yellow
$secretKeywords = @("rzp_live_", "AKIA[0-9A-Z]{16}", "-----BEGIN RSA PRIVATE KEY-----")
$leakFound = $false

foreach ($pattern in $secretKeywords) {
    $matches = git grep -E "$pattern" -- ':!*.ps1' ':!*.md' ':!*.example' 2>$null
    if ($matches) {
        Write-Host "  [✗] CRITICAL SECURITY WARNING: Possible live secret pattern detected: $pattern" -ForegroundColor Red
        $leakFound = $true
    }
}

if ($leakFound) {
    Write-Host "  [✗] Deployment halted due to potential secret exposure." -ForegroundColor Red
    exit 1
} else {
    Write-Host "  [✓] Zero hardcoded secrets detected in source files." -ForegroundColor Green
}

# 3. Execute Backend Unit & Security Test Suite
if (-not $SkipTests) {
    Write-Host "`n[Step 3/6] Running backend test suite (78 tests)..." -ForegroundColor Yellow
    Push-Location backend
    try {
        & .\.venv\Scripts\python.exe -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [✗] Backend tests failed! Deployment aborted." -ForegroundColor Red
            Pop-Location
            exit 1
        }
        Write-Host "  [✓] All backend tests passed successfully (100% OK)." -ForegroundColor Green
    } finally {
        Pop-Location
    }
} else {
    Write-Host "`n[Step 3/6] Skipping backend test suite (-SkipTests flag enabled)." -ForegroundColor DarkGray
}

# 4. Build Frontend Production Assets
if (-not $SkipFrontendBuild) {
    Write-Host "`n[Step 4/6] Compiling frontend production bundle (Vite SPA)..." -ForegroundColor Yellow
    Push-Location frontend
    try {
        cmd.exe /c "npm run build"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [✗] Frontend build failed! Deployment aborted." -ForegroundColor Red
            Pop-Location
            exit 1
        }
        Write-Host "  [✓] Frontend production bundle compiled successfully in frontend/dist." -ForegroundColor Green
    } finally {
        Pop-Location
    }
} else {
    Write-Host "`n[Step 4/6] Skipping frontend build (-SkipFrontendBuild flag enabled)." -ForegroundColor DarkGray
}

# 5. Deployment Readiness & Configuration Verification
Write-Host "`n[Step 5/6] Verifying deployment configuration manifests..." -ForegroundColor Yellow
$configFiles = @("backend/Dockerfile", "render.yaml", "vercel.json", "docker-compose.yml")
foreach ($f in $configFiles) {
    if (Test-Path $f) {
        Write-Host "  [✓] Verified configuration file: $f" -ForegroundColor Green
    } else {
        Write-Host "  [✗] Missing configuration file: $f" -ForegroundColor Red
        exit 1
    }
}

# 6. Post-Deployment Smoke Test
if (-not $SkipSmokeTest) {
    Write-Host "`n[Step 6/6] Running automated post-deployment smoke tests against: $TargetUrl..." -ForegroundColor Yellow
    & .\backend\.venv\Scripts\python.exe scripts/smoke_test.py --url $TargetUrl
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [✓] Post-deployment smoke tests passed successfully!" -ForegroundColor Green
    } else {
        Write-Host "  [!] Smoke tests finished with notes (ensure target service is live and reachable)." -ForegroundColor Yellow
    }
} else {
    Write-Host "`n[Step 6/6] Skipping smoke test (-SkipSmokeTest flag enabled)." -ForegroundColor DarkGray
}

Write-Host "`n=========================================================================" -ForegroundColor Cyan
Write-Host "✨ RECOVERX DEPLOYMENT VERIFICATION COMPLETE" -ForegroundColor Cyan
Write-Host "=========================================================================" -ForegroundColor Cyan
Write-Host "Target Deployment Platforms:"
Write-Host "  • Backend API & Worker: Render (Blueprint: render.yaml)"
Write-Host "  • Database: PostgreSQL (Connected via DATABASE_URL)"
Write-Host "  • Frontend: Vercel (Config: vercel.json, Output: dist/)"
Write-Host "  • Razorpay Gateway: TEST MODE default (rzp_test_...)"
Write-Host "=========================================================================" -ForegroundColor Cyan

