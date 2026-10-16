<#
.SYNOPSIS
  Install inhousecode for the current Windows user.

.DESCRIPTION
  inhousecode runs on bash, which on Windows means Git Bash (shipped with Git
  for Windows). This installer verifies the prerequisites, lets you pick which
  AI CLI backend to use (Copilot CLI, Claude Code CLI, Codex, or Hermes), and drops a
  inhousecode.cmd launcher into a directory on your PATH; the launcher hands
  every invocation to Git Bash. Nothing is copied, so updating this checkout
  updates the tool.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -Harness claude-code -WithSemgrep

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -Harness claude-code -AdversarialModel claude-opus-4
#>

[CmdletBinding()]
param(
    [string]$BinDir = (Join-Path $env:LOCALAPPDATA 'inhousecode\bin'),
    [switch]$WithSemgrep,
    [ValidateSet('copilot', 'claude-code', 'codex', 'hermes')]
    [string]$Harness,
    [string]$AdversarialModel,
    [switch]$NoAdversarial,
    [switch]$FixByDefault,
    [switch]$NoFixByDefault
)

$ErrorActionPreference = 'Stop'
$InhousecodeHome = $PSScriptRoot
if ($FixByDefault -and $NoFixByDefault) {
    throw 'Use only one of -FixByDefault and -NoFixByDefault.'
}
# Git Bash is the only supported bash on Windows; WSL bash cannot see the
# Windows-side AI CLI or the repository paths the gates hand around.
$GitBashCandidates = @(
    "$env:ProgramFiles\Git\bin\bash.exe",
    "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
    "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe"
)

function Write-Ok   { param($m) Write-Host "  OK    $m" -ForegroundColor Green }
function Write-Miss { param($m) Write-Host "  MISS  $m" -ForegroundColor Yellow }

Write-Host "inhousecode installer"
Write-Host "  source: $InhousecodeHome"
Write-Host ""
Write-Host "Checking prerequisites..."

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is required. Install Git for Windows: https://git-scm.com/download/win"
}
Write-Ok 'git'

$bash = $GitBashCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $bash) {
    $gitCmd = (Get-Command git).Source
    $guess = Join-Path (Split-Path (Split-Path $gitCmd)) 'bin\bash.exe'
    if (Test-Path $guess) { $bash = $guess }
}
if (-not $bash) { throw "Git Bash (bash.exe) was not found. Install Git for Windows." }
Write-Ok "Git Bash ($bash)"

$python = @('python3', 'python') |
    ForEach-Object { Get-Command $_ -ErrorAction SilentlyContinue } |
    Select-Object -First 1
if (-not $python) { throw "Python 3 is required." }
Write-Ok "python 3 ($($python.Source))"

if (Get-Command semgrep -ErrorAction SilentlyContinue) {
    Write-Ok 'semgrep'
}
elseif ($WithSemgrep) {
    Write-Host '  Installing semgrep with pip...'
    & $python.Source -m pip install --user semgrep
    Write-Ok 'semgrep installed'
}
else {
    Write-Miss 'semgrep not found - the static gate needs it (pip install semgrep, or re-run with -WithSemgrep)'
}

# --- AI harness selection ------------------------------------------------------
#
# Same Hermes-style choice as install.sh: pick which AI CLI backend runs the
# review, repair, discover, and explain agents. Written into the shipped
# default config so every invocation resolves it without a per-repo override.

$HarnessOptions = @(
    @{ Value = 'copilot';     Label = 'copilot      - GitHub Copilot CLI  (copilot)' }
    @{ Value = 'claude-code'; Label = 'claude-code  - Anthropic Claude Code CLI  (claude)' }
    @{ Value = 'hermes';      Label = 'hermes       - Hermes / Claude Code  (hermes or claude)' }
    @{ Value = 'codex';       Label = 'codex        - OpenAI Codex CLI  (codex)' }
)

if (-not $Harness) {
    if ($Host.UI.RawUI -and -not [Console]::IsInputRedirected) {
        Write-Host ""
        Write-Host "  Which AI CLI do you want inhousecode to use as its backend?"
        Write-Host "  (This runs the AI code review, repairs, discover, and explain sessions.)"
        Write-Host ""
        for ($i = 0; $i -lt $HarnessOptions.Count; $i++) {
            Write-Host ("    [{0}] {1}" -f ($i + 1), $HarnessOptions[$i].Label)
        }
        $reply = Read-Host "`n  Pick a number [1]"
        $index = 0
        if ($reply -match '^[0-9]+$') { $index = [int]$reply - 1 }
        if ($index -lt 0 -or $index -ge $HarnessOptions.Count) { $index = 0 }
        $Harness = $HarnessOptions[$index].Value
    }
    else {
        # Non-interactive default: copilot (backward compatible).
        $Harness = 'copilot'
    }
}

Write-Host ""
Write-Ok "AI harness: $Harness"

switch ($Harness) {
    'copilot' {
        if (Get-Command copilot -ErrorAction SilentlyContinue) {
            Write-Ok 'Copilot CLI'
        }
        else {
            Write-Miss 'Copilot CLI not found - the AI gate needs it (https://github.com/github/copilot-cli)'
        }
    }
    'claude-code' {
        if (Get-Command claude -ErrorAction SilentlyContinue) {
            Write-Ok 'Claude Code CLI'
        }
        else {
            Write-Miss 'Claude Code CLI not found - install it: npm install -g @anthropic-ai/claude-code'
        }
    }
    'hermes' {
        if (Get-Command hermes -ErrorAction SilentlyContinue) {
            Write-Ok 'Hermes CLI'
        }
        elseif (Get-Command claude -ErrorAction SilentlyContinue) {
            Write-Ok 'Hermes: falling back to Claude Code CLI'
        }
        else {
            Write-Miss 'Hermes CLI not found - install it, or install Claude Code: npm install -g @anthropic-ai/claude-code'
        }
    }
    'codex' {
        if (Get-Command codex -ErrorAction SilentlyContinue) {
            Write-Ok 'Codex CLI'
        }
        else {
            Write-Miss 'Codex CLI not found - install it: npm install -g @openai/codex'
        }
    }
}

# --- adversarial review model -------------------------------------------------
#
# The heavy, opt-in second mode: several lenses each review a whole PR on a
# DIFFERENT model than the primary review, on the same harness. Setting the
# model turns the mode on; it is still invoked per run with --adversarial.

$AdversarialEnabled = $false
if ($NoAdversarial) {
    $AdversarialModel = ''
}
elseif (-not $AdversarialModel) {
    if ($Host.UI.RawUI -and -not [Console]::IsInputRedirected) {
        Write-Host ""
        Write-Host "  Adversarial review (optional): the deep, final review for a whole PR."
        Write-Host "  Instead of one reviewer, several independent critics each attack the"
        Write-Host "  change from a different angle (correctness, design, simplicity) on a"
        Write-Host "  DIFFERENT model than your normal review, then a lead pass merges them"
        Write-Host "  into one verdict. Run it before merging, not on every commit."
        $reply = Read-Host "  Model id for adversarial lenses (blank = disabled)"
        if ($reply) { $AdversarialModel = $reply; $AdversarialEnabled = $true }
    }
}
else {
    $AdversarialEnabled = $true
}
if ($AdversarialModel) { $AdversarialEnabled = $true }

if ($AdversarialEnabled) {
    if ($AdversarialModel) {
        Write-Ok "Adversarial review: enabled (model: $AdversarialModel)"
    }
    else {
        Write-Ok "Adversarial review: enabled (lenses use the primary review model)"
    }
}
else {
    Write-Ok "Adversarial review: disabled (enable later in config)"
}

# --- default repair policy ----------------------------------------------------

$FixByDefaultValue = $null
if ($FixByDefault) {
    $FixByDefaultValue = $true
}
elseif ($NoFixByDefault) {
    $FixByDefaultValue = $false
}
elseif ($Host.UI.RawUI -and -not [Console]::IsInputRedirected) {
    Write-Host ""
    Write-Host "  Automatic repair is optional. When enabled, every review repairs all"
    Write-Host "  static and AI findings, then re-reviews the result. --no-fix still wins."
    $reply = Read-Host "  Fix findings by default? [y/N]"
    $FixByDefaultValue = $reply -match '^[Yy]([Ee][Ss])?$'
}

if ($null -eq $FixByDefaultValue) {
    Write-Ok "Fix findings by default: unchanged"
}
elseif ($FixByDefaultValue) {
    Write-Ok "Fix findings by default: enabled"
}
else {
    Write-Ok "Fix findings by default: disabled"
}

# --- write the harness choice into the default config -------------------------
#
# The installer's pick is recorded in the shipped default so every invocation
# resolves it without a per-repo override. A team can still override it in
# .inhousecode/config.json for a specific repository.

$defaultConfigPath = Join-Path $InhousecodeHome 'config\review.config.default.json'
$cfg = Get-Content -Raw -Path $defaultConfigPath | ConvertFrom-Json
$cfg.harness = $Harness
if (-not $cfg.adversarial) {
    $cfg | Add-Member -NotePropertyName adversarial -NotePropertyValue ([pscustomobject]@{ enabled = $false; model = ''; maxLenses = 4 }) -Force
}
$cfg.adversarial.enabled = $AdversarialEnabled
$cfg.adversarial.model = [string]$AdversarialModel
if ($null -ne $FixByDefaultValue) {
    if (-not $cfg.review) {
        $cfg | Add-Member -NotePropertyName review -NotePropertyValue ([pscustomobject]@{ fixByDefault = $false }) -Force
    }
    $cfg.review.fixByDefault = [bool]$FixByDefaultValue
}
$cfg | ConvertTo-Json -Depth 20 | Set-Content -Path $defaultConfigPath -Encoding UTF8

New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$launcher = Join-Path $BinDir 'inhousecode.cmd'
$unixHome = $InhousecodeHome -replace '\\', '/'
@"
@echo off
REM Generated by the inhousecode installer. Points at the checkout below.
"$bash" "$unixHome/bin/inhousecode" %*
"@ | Set-Content -Path $launcher -Encoding ASCII

Write-Host ""
Write-Host "Installed launcher: $launcher"

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable('Path', "$userPath;$BinDir", 'User')
    Write-Host "Added $BinDir to your user PATH. Open a new terminal to pick it up."
}

Write-Host @"

AI harness: $Harness
  (change later: edit config\review.config.default.json or set "harness"
   in your repo's .inhousecode\config.json)

Next steps, in any repository you want reviewed:

  cd C:\path\to\your\repo
  inhousecode init            # creates .inhousecode\ configuration
  inhousecode discover        # optional: proposes governed candidate knowledge
  inhousecode install-hooks   # installs the trigger you configured
  inhousecode doctor          # verify everything resolves

Then just work normally. Run 'inhousecode review' any time for an ad-hoc pass.
"@
