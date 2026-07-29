<#
.SYNOPSIS
    Builds Intune-Install-Open-Folder.ps1 - a single self-contained file you can
    paste into Intune as a platform script.

.DESCRIPTION
    Intune platform scripts are one file, but the installer needs
    open-folder.vbs alongside it. So this generates a version with the VBS
    embedded, keeping open-folder.vbs as the one place it's actually edited.

    Run this again whenever you change open-folder.vbs, and re-upload the
    result to Intune.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$vbsPath = Join-Path $PSScriptRoot 'open-folder.vbs'
$outPath = Join-Path $PSScriptRoot 'Intune-Install-Open-Folder.ps1'

if (-not (Test-Path $vbsPath)) { throw "Can't find open-folder.vbs in $PSScriptRoot" }
$vbs = Get-Content $vbsPath -Raw

# The VBS gets embedded in a single-quoted here-string. A line that is exactly
# '@ would close it early and produce a broken script, so refuse rather than
# ship something that half-works.
foreach ($line in $vbs -split "`r?`n") {
    if ($line -match "^\s*'@") {
        throw ("open-folder.vbs line `"$line`" would terminate the here-string. " +
               "Reword that comment and run this again.")
    }
}

$generated = @"
<#
    GENERATED FILE - do not edit.
    Built from open-folder.vbs by "Make Intune Script.ps1" on $(Get-Date -Format 'yyyy-MM-dd').
    Edit open-folder.vbs and re-run that instead.

    Intune platform script. Settings that matter:
      Run using logged-on credentials : No   (needs to run as System, for HKLM)
      Enforce script signature check  : No
      Run in 64-bit PowerShell host   : Yes

    Makes the VS Search "Open folder" button open Explorer on this machine,
    for every user of it. Users are never asked to do anything.
#>
`$ErrorActionPreference = 'Stop'

`$installDir  = Join-Path `$env:ProgramData 'VS Search'
`$helperPath  = Join-Path `$installDir 'open-folder.vbs'
`$protocolKey = 'HKLM:\SOFTWARE\Classes\vsfolder'

`$helper = @'
$vbs
'@

try {
    New-Item -ItemType Directory -Path `$installDir -Force | Out-Null
    Set-Content -Path `$helperPath -Value `$helper -Encoding ASCII

    New-Item -Path `$protocolKey -Force | Out-Null
    Set-ItemProperty -Path `$protocolKey -Name '(default)'    -Value 'URL:VS Search folder'
    Set-ItemProperty -Path `$protocolKey -Name 'URL Protocol' -Value ''

    `$commandKey = Join-Path `$protocolKey 'shell\open\command'
    New-Item -Path `$commandKey -Force | Out-Null
    Set-ItemProperty -Path `$commandKey -Name '(default)' ``
        -Value ('wscript.exe "{0}" "%1"' -f `$helperPath)

    if (-not ((Test-Path `$helperPath) -and (Test-Path `$commandKey))) {
        Write-Error 'Registry key or helper file missing after install.'
        exit 1
    }

    Write-Output "Open folder installed for all users of `$env:COMPUTERNAME."
    exit 0
}
catch {
    # Intune reads the exit code, so fail loudly rather than silently.
    Write-Error `$_.Exception.Message
    exit 1
}
"@

Set-Content -Path $outPath -Value $generated -Encoding UTF8
Write-Output "Wrote $outPath"
Write-Output "  embedded open-folder.vbs ($($vbs.Length) chars)"
Write-Output "Upload that file to Intune as a Windows platform script."
