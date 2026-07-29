<#
.SYNOPSIS
    Makes the VS Search "Open folder" button work on this computer, for every
    user of it. Staff never run this or see it.

.DESCRIPTION
    The search page can't reach the desktop by itself - browsers refuse to
    follow a file:// link from a web page. This registers a "vsfolder:" handler
    so the page can hand a folder to Windows, and Windows opens Explorer.

    Run it once per computer, as an administrator. Three ways to do that
    without walking to anyone's desk:

      * Intune / MDM     - add as a platform script (run as System). Package it
                           together with open-folder.vbs; the script needs that
                           file sitting next to it.
      * A support tool   - ScreenConnect, TeamViewer, an RMM agent: run it from
                           the network copy of the proposal-automation folder.
      * Deploy script    - "Deploy Open Folder.ps1" pushes this to a list of
                           computers over PowerShell remoting.

    Writes to HKLM, so it covers everyone who signs in to the machine. Safe to
    run again - it overwrites its own settings and nothing else. The per-user
    version ("Enable Open Folder.bat") keeps working alongside it.

.PARAMETER Uninstall
    Remove the handler and the helper script instead of installing.

.EXAMPLE
    .\"Install Open Folder (all users).ps1"

.EXAMPLE
    .\"Install Open Folder (all users).ps1" -Uninstall
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [switch] $Uninstall
)

$ErrorActionPreference = 'Stop'

$InstallDir  = Join-Path $env:ProgramData 'VS Search'
$HelperPath  = Join-Path $InstallDir 'open-folder.vbs'
$ProtocolKey = 'HKLM:\SOFTWARE\Classes\vsfolder'

function Test-Administrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Administrator)) {
    throw ('This needs to run as an administrator - it writes a setting that ' +
           'covers every user of the computer. Right-click PowerShell and pick ' +
           '"Run as administrator", or let Intune run it as System.')
}

# --- uninstall ------------------------------------------------------------
if ($Uninstall) {
    if (Test-Path $ProtocolKey) {
        if ($PSCmdlet.ShouldProcess($ProtocolKey, 'Remove registry key')) {
            Remove-Item $ProtocolKey -Recurse -Force
        }
    }
    if (Test-Path $InstallDir) {
        if ($PSCmdlet.ShouldProcess($InstallDir, 'Remove folder')) {
            Remove-Item $InstallDir -Recurse -Force
        }
    }
    Write-Output "Removed. Open folder will copy the path instead of opening it."
    return
}

# --- find the helper ------------------------------------------------------
# It has to travel with this script. Intune platform scripts are single-file,
# so package this as a Win32 app (which allows more than one file) rather than
# splitting the two apart.
$source = Join-Path $PSScriptRoot 'open-folder.vbs'
if (-not (Test-Path $source)) {
    throw ("Can't find open-folder.vbs next to this script (looked in " +
           "$PSScriptRoot). Copy the whole proposal-automation folder, not " +
           "just the .ps1.")
}

# --- install --------------------------------------------------------------
if ($PSCmdlet.ShouldProcess($env:COMPUTERNAME, 'Install the vsfolder: handler')) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Copy-Item $source $HelperPath -Force

    New-Item -Path $ProtocolKey -Force | Out-Null
    Set-ItemProperty -Path $ProtocolKey -Name '(default)'    -Value 'URL:VS Search folder'
    # An empty "URL Protocol" value is what tells Windows this is a
    # clickable-from-a-browser scheme. The name matters, the value doesn't.
    Set-ItemProperty -Path $ProtocolKey -Name 'URL Protocol' -Value ''

    $commandKey = Join-Path $ProtocolKey 'shell\open\command'
    New-Item -Path $commandKey -Force | Out-Null
    Set-ItemProperty -Path $commandKey -Name '(default)' `
        -Value ('wscript.exe "{0}" "%1"' -f $HelperPath)
}

# --- verify ---------------------------------------------------------------
# Report what's actually on disk and in the registry, not just "done" - a
# deployment tool's exit code is the only thing anyone will look at.
$installed = (Test-Path $HelperPath) -and (Test-Path "$ProtocolKey\shell\open\command")
if (-not $installed -and -not $WhatIfPreference) {
    throw "Install did not take - the registry key or helper file is missing."
}

Write-Output "Open folder is set up for all users of $env:COMPUTERNAME."
Write-Output "  helper : $HelperPath"
Write-Output "  handler: $ProtocolKey"
Write-Output "The first click asks the browser for permission - tick 'Always allow'."
