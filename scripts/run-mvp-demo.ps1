param(
  [string]$RunId = 'run-2026-02-28-mvp',
  [string]$WorkspaceRoot = 'C:\Users\User\Desktop\Codingyay',
  [string]$PlannerWorktree = 'planner',
  [string]$ImplAWorktree = 'impl-a',
  [string]$ImplBWorktree = 'impl-b',
  [string]$IntegratorWorktree = 'integrator',
  [string]$ImplABranchPrimary = 'mvp/person-b-impl-a',
  [string]$ImplBBranchPrimary = 'mvp/person-c-impl-b',
  [string]$ImplABranchFallback = 'mvp/impl-a',
  [string]$ImplBBranchFallback = 'mvp/impl-b'
)

$ErrorActionPreference = 'Stop'

function Test-GitRef {
  param([string]$Ref)
  try {
    & git show-ref --verify --quiet $Ref | Out-Null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  }

  return $false
}

function Resolve-Branch {
  param([string[]]$BranchCandidates)

  foreach ($branch in $BranchCandidates) {
    $localRef = Join-Path 'refs/heads' $branch
    $remoteRef = Join-Path 'refs/remotes/origin' $branch
    if (Test-GitRef $localRef -or Test-GitRef $remoteRef) {
      return $branch
    }
  }

  return $BranchCandidates[0]
}

$Paths = [ordered]@{
  Planner    = Join-Path $WorkspaceRoot ("codex-worktrees\$PlannerWorktree")
  ImplA      = Join-Path $WorkspaceRoot ("codex-worktrees\$ImplAWorktree")
  ImplB      = Join-Path $WorkspaceRoot ("codex-worktrees\$ImplBWorktree")
  Integrator = Join-Path $WorkspaceRoot ("codex-worktrees\$IntegratorWorktree")
}

$Branches = [ordered]@{
  ImplA = Resolve-Branch @($ImplABranchPrimary, $ImplABranchFallback)
  ImplB = Resolve-Branch @($ImplBBranchPrimary, $ImplBBranchFallback)
}

$PacketDir = Join-Path $Paths.Integrator "artifacts\pr-packets\$RunId"
$ContractCheckPath = Join-Path $PacketDir 'contract-check.json'
$RequiredPacketFiles = @(
  'diff.patch',
  'test-logs.txt',
  'contract-check.json',
  'contract-check.diff.txt',
  'impact-report.json',
  'summary.md'
)

function Write-Header {
  param([string]$Text)
  Write-Host "`n== $Text ==" -ForegroundColor Cyan
}

function Invoke-Step {
  param(
    [string]$Label,
    [string]$Command,
    [string[]]$Arguments,
    [string]$WorkingDirectory,
    [int]$ExpectedExitCode = 0,
    [switch]$AllowFailure
  )

  Write-Host "-> $Label"
  Write-Host "command: $Command $($Arguments -join ' ')" -ForegroundColor Gray
  Push-Location $WorkingDirectory
  try {
    & $Command @Arguments
    $exitCode = [int]$LASTEXITCODE
  } finally {
    Pop-Location
  }

  Write-Host "exit: $exitCode"

  if (-not $AllowFailure -and $exitCode -ne $ExpectedExitCode) {
    throw "$Label failed. Expected exit code $ExpectedExitCode, got $exitCode."
  }

  return $exitCode
}

function Assert-Exists([string]$Path, [string]$Label) {
  if (-not (Test-Path $Path)) {
    throw "Missing $Label path: $Path"
  }
}

function Assert-JsonField {
  param(
    [string]$Path,
    [string]$Field,
    [string]$Expected
  )
  $obj = Get-Content $Path -Raw | ConvertFrom-Json
  $actual = [string]$obj.$Field
  if ($actual -ne $Expected) {
    throw "Expected $Field='$Expected' in $Path but got '$actual'."
  }
}

# 0) Pre-flight checks
Write-Header 'Pre-flight: role worktrees and required scripts'
$Paths.GetEnumerator() | ForEach-Object {
  Assert-Exists $_.Value "$($_.Key) worktree"
}
Assert-Exists (Join-Path $Paths.Integrator 'scripts\multiagent\contract-check.mjs') 'contract check script'
Assert-Exists (Join-Path $Paths.Integrator 'scripts\multiagent\generate-pr-packet.mjs') 'packet generator script'

# 1) Planner publish / evidence visibility
Write-Header 'Planner publish'
$intentPath = Join-Path $Paths.Planner "artifacts\coordination\$RunId\intent.json"
$plannerImpactPath = Join-Path $Paths.Planner "artifacts\coordination\$RunId\impact-planner.json"
Assert-Exists $intentPath 'planner intent'
Assert-Exists $plannerImpactPath 'planner impact'
Get-Content $intentPath -Raw | Write-Output
Get-Content $plannerImpactPath -Raw | Write-Output

Write-Host "Using branches: impl-a=$($Branches.ImplA), impl-b=$($Branches.ImplB)"

# 2) Implementer-A run (protocol producer)
Write-Header 'Implementer-A run'
Invoke-Step -Label 'git status (impl-a)' -Command 'git' -Arguments @('status','--short') -WorkingDirectory $Paths.ImplA
Invoke-Step -Label 'fixture test for schema generator' -Command 'cargo' -Arguments @('test','-p','codex-app-server-protocol','schema_fixtures_match_generated') -WorkingDirectory (Join-Path $Paths.ImplA 'codex-rs')
Invoke-Step -Label 're-generate fixture bundle (impl-a)' -Command 'cargo' -Arguments @('run','-p','codex-app-server-protocol','--bin','write_schema_fixtures','--','--schema-root','artifacts/tmp-schema-run') -WorkingDirectory (Join-Path $Paths.ImplA 'codex-rs')
Invoke-Step -Label 'impl-a scope check (protocol diff)' -Command 'git' -Arguments @('diff','--name-only','--','codex-rs/app-server-protocol/src/protocol/v2.rs') -WorkingDirectory $Paths.ImplA

# 3) Implementer-B run (contract pin)
Write-Header 'Implementer-B run'
Invoke-Step -Label 'git status (impl-b)' -Command 'git' -Arguments @('status','--short') -WorkingDirectory $Paths.ImplB
Assert-Exists (Join-Path $Paths.ImplB 'contracts\app-schema.expected.json') 'app schema expected contract'
Invoke-Step -Label 'impl-b scope check (contract file touch)' -Command 'git' -Arguments @('diff','--name-only','--','contracts/app-schema.expected.json') -WorkingDirectory $Paths.ImplB

# 4) Integrator: merge impl-a and show gate failure
Write-Header 'Integrator merge + gate fail scenario'
Push-Location $Paths.Integrator
try {
  Invoke-Step -Label 'checkout clean integrator workspace' -Command 'git' -Arguments @('status','--short') -WorkingDirectory $Paths.Integrator | Out-Null
  Invoke-Step -Label "merge $($Branches.ImplA)" -Command 'git' -Arguments @('merge',$Branches.ImplA,'--no-edit') -WorkingDirectory $Paths.Integrator
  $codeFail = Invoke-Step -Label 'contract check (expected FAIL)' -Command 'node' -Arguments @('scripts/multiagent/contract-check.mjs','--run-id',$RunId) -WorkingDirectory $Paths.Integrator -AllowFailure
  if ($codeFail -ne 1) {
    Write-Host "Warning: contract-check expected fail code 1, got $codeFail"
  }
  if (Test-Path $ContractCheckPath) {
    $status = (Get-Content $ContractCheckPath -Raw | ConvertFrom-Json).status
    Write-Host "Observed contract-check status: $status"
  }

  # 5) Integrator: merge impl-b and show gate pass
  Write-Header 'Integrator merge + gate pass scenario'
  Invoke-Step -Label "merge $($Branches.ImplB)" -Command 'git' -Arguments @('merge',$Branches.ImplB,'--no-edit') -WorkingDirectory $Paths.Integrator
  $codePass = Invoke-Step -Label 'contract check (expected PASS)' -Command 'node' -Arguments @('scripts/multiagent/contract-check.mjs','--run-id',$RunId) -WorkingDirectory $Paths.Integrator
  if ($codePass -ne 0) {
    Write-Host "Warning: contract-check expected pass code 0, got $codePass"
  }
  if (Test-Path $ContractCheckPath) {
    $status = (Get-Content $ContractCheckPath -Raw | ConvertFrom-Json).status
    Write-Host "Observed contract-check status: $status"
  }

  # 6) Packet generation
  Write-Header 'Generate PR packet'
  Invoke-Step -Label 'generate-pr-packet.mjs' -Command 'node' -Arguments @('scripts/multiagent/generate-pr-packet.mjs','--run-id',$RunId) -WorkingDirectory $Paths.Integrator

} finally {
  Pop-Location
}

# 7) Artifact verification
Write-Header 'Artifact verification'
foreach ($file in $RequiredPacketFiles) {
  $full = Join-Path $PacketDir $file
  Assert-Exists $full "packet artifact $file"
  Write-Host "OK: $full"
}

Write-Header 'Run result'
$summary = Get-Content (Join-Path $PacketDir 'summary.md') -Raw
Write-Host $summary
Write-Host "`nArtifacts directory: $PacketDir"
Write-Host 'Run completed successfully.' -ForegroundColor Green
