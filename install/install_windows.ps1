<#
.SYNOPSIS
    Register the gdrivereveal:// protocol handler for the current user.

.DESCRIPTION
    Writes HKCU:\Software\Classes\gdrivereveal so Firefox (or any browser) can hand
    gdrivereveal:// links to the local helper. Per-user, so no administrator rights are
    needed and nothing is changed for other accounts on the machine.

    All paths are derived from this script's own location, so the repo can be cloned
    anywhere. Nothing machine-specific is written into the repo.

.PARAMETER Uninstall
    Remove the registration instead of creating it.

.PARAMETER Verify
    Report what is currently registered and check that the helper runs, without changing
    anything.

.EXAMPLE
    .\install\install_windows.ps1
    .\install\install_windows.ps1 -Verify
    .\install\install_windows.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$Verify
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Helper = Join-Path $RepoRoot 'helper\drive-reveal.py'
$IconSource = Join-Path $RepoRoot 'extension\icons\reveal.svg'
$RegPath = 'HKCU:\Software\Classes\gdrivereveal'

function Find-PythonW {
    <#
        pythonw.exe rather than python.exe: the handler is launched by the OS with no
        console, and python.exe would flash a black window on every click.
    #>
    $candidates = @()

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        # The launcher knows where the real interpreter lives; ask it.
        try {
            $resolved = & $py.Source -c "import sys, pathlib; print(pathlib.Path(sys.executable).with_name('pythonw.exe'))" 2>$null
            if ($resolved) { $candidates += $resolved.Trim() }
        } catch {}
    }

    $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $candidates += (Join-Path (Split-Path -Parent $pythonCmd.Source) 'pythonw.exe')
    }

    $pythonwCmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($pythonwCmd) { $candidates += $pythonwCmd.Source }

    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) { return (Resolve-Path -LiteralPath $c).Path }
    }
    return $null
}

function Show-Registration {
    if (-not (Test-Path $RegPath)) {
        Write-Host 'gdrivereveal:// is not registered.' -ForegroundColor Yellow
        return $false
    }
    $cmdKey = Join-Path $RegPath 'shell\open\command'
    $cmd = (Get-ItemProperty -Path $cmdKey -Name '(default)' -ErrorAction SilentlyContinue).'(default)'
    Write-Host 'gdrivereveal:// is registered as:' -ForegroundColor Green
    Write-Host "  $cmd"
    return $true
}

# ----------------------------------------------------------------------------- verify

if ($Verify) {
    $registered = Show-Registration

    Write-Host "`nRepo:   $RepoRoot"
    Write-Host "Helper: $Helper  $(if (Test-Path $Helper) { '(found)' } else { '(MISSING)' })"

    $pythonw = Find-PythonW
    Write-Host "pythonw: $(if ($pythonw) { $pythonw } else { 'NOT FOUND' })"

    Write-Host "`nResolving your My Drive root as a smoke test:"
    $python = (Get-Command python.exe -ErrorAction SilentlyContinue)
    if ($python -and (Test-Path $Helper)) {
        & $python.Source -E $Helper 'https://drive.google.com/drive/my-drive' --print
        if ($LASTEXITCODE -eq 0) {
            Write-Host 'Helper works.' -ForegroundColor Green
        } else {
            Write-Host "Helper exited $LASTEXITCODE." -ForegroundColor Red
        }
    } else {
        Write-Host 'Skipped: python.exe or the helper script was not found.' -ForegroundColor Yellow
    }
    exit $(if ($registered) { 0 } else { 1 })
}

# -------------------------------------------------------------------------- uninstall

if ($Uninstall) {
    if (Test-Path $RegPath) {
        Remove-Item -Path $RegPath -Recurse -Force
        Write-Host 'Removed the gdrivereveal:// registration.' -ForegroundColor Green
    } else {
        Write-Host 'Nothing to remove; gdrivereveal:// was not registered.' -ForegroundColor Yellow
    }
    Write-Host 'Firefox may still list the old handler until you restart it.'
    exit 0
}

# ---------------------------------------------------------------------------- install

if (-not (Test-Path -LiteralPath $Helper)) {
    throw "Helper not found at $Helper. Run this script from inside the drive-reveal checkout."
}

$pythonw = Find-PythonW
if (-not $pythonw) {
    throw 'Could not find pythonw.exe. Install Python 3.9+ from python.org and re-run this script.'
}

# "%1" must stay quoted: Drive folder names routinely contain spaces and ampersands.
# -E makes python ignore PYTHON* variables. The handler inherits the environment of
# whatever launched the browser, and apps that bundle their own interpreter (FreeCAD,
# Blender, Houdini) export PYTHONHOME; without -E that kills the interpreter at startup
# with "Failed to import encodings module".
$command = '"{0}" -E "{1}" --gui "%1"' -f $pythonw, $Helper

New-Item -Path $RegPath -Force | Out-Null
New-ItemProperty -Path $RegPath -Name '(default)' -Value 'URL:Reveal in Drive folder' -PropertyType String -Force | Out-Null
# The presence of this empty value is what marks the key as a URL protocol.
New-ItemProperty -Path $RegPath -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null

$cmdKey = Join-Path $RegPath 'shell\open\command'
New-Item -Path $cmdKey -Force | Out-Null
New-ItemProperty -Path $cmdKey -Name '(default)' -Value $command -PropertyType String -Force | Out-Null

if (Test-Path -LiteralPath $IconSource) {
    $iconKey = Join-Path $RegPath 'DefaultIcon'
    New-Item -Path $iconKey -Force | Out-Null
    New-ItemProperty -Path $iconKey -Name '(default)' -Value $pythonw -PropertyType String -Force | Out-Null
}

Write-Host 'Registered gdrivereveal:// for the current user.' -ForegroundColor Green
Write-Host "  $command"
Write-Host ''
Write-Host 'Next:'
Write-Host '  1. Install the browser side: drag the bookmarklet from bookmarklet\install.html,'
Write-Host '     or load extension\ in Firefox via about:debugging.'
Write-Host '  2. On the first click Firefox will ask which application to use. Pick it and'
Write-Host '     tick "Remember my choice".'
Write-Host ''
Write-Host 'Check it with:  .\install\install_windows.ps1 -Verify'
