$ErrorActionPreference = "Stop"

$PackageRoot = $PSScriptRoot
$DemoRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("proofed_demo_" + [guid]::NewGuid().ToString("N"))
[System.IO.Directory]::CreateDirectory($DemoRoot) | Out-Null
Copy-Item -Path (Join-Path $PackageRoot "examples\false-completion\*") -Destination $DemoRoot -Recurse -Force

$env:PIP_NO_INDEX = "1"
Push-Location $PackageRoot
& py -3 -m pip install --no-build-isolation --no-deps .
$InstallExit = $LASTEXITCODE
Pop-Location

$script:UseInstalledProofed = ($InstallExit -eq 0)
if (-not $script:UseInstalledProofed) {
    $env:PYTHONPATH = Join-Path $PackageRoot "src"
    Write-Host "Offline install was unavailable; using the packaged source directly."
}

function Invoke-Proofed {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ProofedArgs)
    if ($script:UseInstalledProofed) {
        & py -3 -m proofed.cli @ProofedArgs
    }
    else {
        & py -3 -m proofed.cli @ProofedArgs
    }
    $script:ProofedExit = $LASTEXITCODE
}

Push-Location $DemoRoot
if (Get-Command git -ErrorAction SilentlyContinue) {
    & git init -q
    & git add .
    & git -c user.name=demo -c user.email=demo@example.invalid commit -qm baseline
}

Invoke-Proofed init
if ($script:ProofedExit -ne 0) { throw "proofed init failed" }
Invoke-Proofed run . --intent "verify integer addition"
if ($script:ProofedExit -ne 0) { throw "proofed run failed" }

Write-Host "`nExpected red decision:"
Invoke-Proofed verify
if ($script:ProofedExit -ne 2) { throw "expected verify exit 2, got $script:ProofedExit" }

Write-Host "`nExpected green decision:"
Invoke-Proofed verify --run-tests
if ($script:ProofedExit -ne 0) { throw "proofed test verification failed" }

$Receipt = Get-ChildItem -LiteralPath (Join-Path $DemoRoot ".proofed\receipts") -Filter "completion-*.json" | Select-Object -First 1
Invoke-Proofed check-receipt $Receipt.FullName --current .
if ($script:ProofedExit -ne 0) { throw "receipt verification failed" }
Pop-Location

Write-Host "`nProofed v0.1-alpha red/green demo passed."
Write-Host ("Demo directory: " + $DemoRoot)
