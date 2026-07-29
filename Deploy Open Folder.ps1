<#
.SYNOPSIS
    Installs the VS Search "Open folder" handler on a list of computers, so
    nobody has to run anything at their own desk.

.DESCRIPTION
    Pushes open-folder.vbs to each computer and registers the "vsfolder:"
    handler for all users of it. Reports one line per computer at the end.

    Needs, on each computer you're targeting:
      * PowerShell remoting enabled          (Enable-PSRemoting -Force)
      * your account to be a local admin there

    Neither is on by default on Windows workstations, and turning them on
    needs the same access you're trying to get - so this is the right tool for
    servers and for machines your management tooling already reaches, not for
    bootstrapping a workgroup from scratch. If -Check tells you every machine
    is unreachable, deploy "Install Open Folder (all users).ps1" through Intune
    or your remote-support tool instead; it does the same work locally.

    On a workgroup (no domain), also tell this computer which machines it may
    authenticate to, once:
        Set-Item WSMan:\localhost\Client\TrustedHosts -Value 'PC1,PC2' -Force
    and pass -Credential (a local admin on the targets).

.PARAMETER ComputerName
    Computers to install on. Accepts pipeline input.

.PARAMETER ComputerListFile
    Text file of computer names, one per line. Blank lines and lines starting
    with # are ignored.

.PARAMETER Credential
    Account to connect with. Needed on a workgroup; on a domain your own
    admin account is usually fine.

.PARAMETER Check
    Only test whether each computer can be reached. Changes nothing.

.PARAMETER Uninstall
    Remove the handler from each computer instead of installing.

.EXAMPLE
    .\"Deploy Open Folder.ps1" -ComputerName OFFICE-PC-1, OFFICE-PC-2

.EXAMPLE
    .\"Deploy Open Folder.ps1" -ComputerListFile .\office-pcs.txt -Check

.EXAMPLE
    .\"Deploy Open Folder.ps1" -ComputerListFile .\office-pcs.txt -Credential (Get-Credential)
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(ValueFromPipeline, Position = 0)]
    [string[]] $ComputerName,

    [string] $ComputerListFile,

    [System.Management.Automation.PSCredential] $Credential,

    [switch] $Check,

    [switch] $Uninstall
)

begin {
    $ErrorActionPreference = 'Stop'
    $targets = [System.Collections.Generic.List[string]]::new()

    $helper = Join-Path $PSScriptRoot 'open-folder.vbs'
    if (-not (Test-Path $helper)) {
        throw ("Can't find open-folder.vbs next to this script (looked in " +
               "$PSScriptRoot). Copy the whole proposal-automation folder.")
    }
    # Read it here, once, and send the text to each machine. That way the
    # targets don't need to reach the network share themselves.
    $helperText = Get-Content $helper -Raw
}

process {
    foreach ($name in $ComputerName) {
        if ($name) { $targets.Add($name.Trim()) }
    }
}

end {
    if ($ComputerListFile) {
        if (-not (Test-Path $ComputerListFile)) {
            throw "Computer list not found: $ComputerListFile"
        }
        Get-Content $ComputerListFile |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -and -not $_.StartsWith('#') } |
            ForEach-Object { $targets.Add($_) }
    }

    $targets = $targets | Select-Object -Unique
    if (-not $targets) {
        throw "No computers given. Use -ComputerName or -ComputerListFile."
    }

    Write-Output "$($targets.Count) computer(s) to process."

    # What actually runs on each machine. Deliberately self-contained - it can't
    # call functions from this script, because it executes over there.
    $payload = {
        param($HelperText, $Remove)

        $installDir  = Join-Path $env:ProgramData 'VS Search'
        $helperPath  = Join-Path $installDir 'open-folder.vbs'
        $protocolKey = 'HKLM:\SOFTWARE\Classes\vsfolder'

        try {
            if ($Remove) {
                if (Test-Path $protocolKey) { Remove-Item $protocolKey -Recurse -Force }
                if (Test-Path $installDir)  { Remove-Item $installDir -Recurse -Force }
                return [pscustomobject]@{ Result = 'Removed'; Detail = '' }
            }

            New-Item -ItemType Directory -Path $installDir -Force | Out-Null
            Set-Content -Path $helperPath -Value $HelperText -Encoding ASCII

            New-Item -Path $protocolKey -Force | Out-Null
            Set-ItemProperty -Path $protocolKey -Name '(default)'    -Value 'URL:VS Search folder'
            Set-ItemProperty -Path $protocolKey -Name 'URL Protocol' -Value ''

            $commandKey = Join-Path $protocolKey 'shell\open\command'
            New-Item -Path $commandKey -Force | Out-Null
            Set-ItemProperty -Path $commandKey -Name '(default)' `
                -Value ('wscript.exe "{0}" "%1"' -f $helperPath)

            if (-not ((Test-Path $helperPath) -and (Test-Path $commandKey))) {
                return [pscustomobject]@{ Result = 'Failed'; Detail = 'setting did not stick' }
            }
            return [pscustomobject]@{ Result = 'Installed'; Detail = $helperPath }
        }
        catch {
            return [pscustomobject]@{ Result = 'Failed'; Detail = $_.Exception.Message }
        }
    }

    $common = @{}
    if ($Credential) { $common['Credential'] = $Credential }

    $report = foreach ($pc in $targets) {
        # Pre-flight, so an unreachable machine gets a sentence a person can
        # act on rather than a wall of WSMan XML.
        try {
            $null = Test-WSMan -ComputerName $pc @common -ErrorAction Stop
        }
        catch {
            [pscustomobject]@{
                Computer = $pc
                Result   = 'Unreachable'
                Detail   = 'PowerShell remoting not answering - run "Enable-PSRemoting -Force" there, or deploy via Intune instead'
            }
            continue
        }

        if ($Check) {
            [pscustomobject]@{ Computer = $pc; Result = 'Reachable'; Detail = 'ready to deploy' }
            continue
        }

        $action = if ($Uninstall) { 'Remove the vsfolder: handler' }
                  else { 'Install the vsfolder: handler' }
        if (-not $PSCmdlet.ShouldProcess($pc, $action)) { continue }

        try {
            $r = Invoke-Command -ComputerName $pc @common -ScriptBlock $payload `
                    -ArgumentList $helperText, [bool]$Uninstall -ErrorAction Stop
            [pscustomobject]@{ Computer = $pc; Result = $r.Result; Detail = $r.Detail }
        }
        catch {
            [pscustomobject]@{
                Computer = $pc
                Result   = 'Failed'
                Detail   = $_.Exception.Message
            }
        }
    }

    $report | Format-Table -AutoSize

    $bad = @($report | Where-Object { $_.Result -in 'Failed', 'Unreachable' })
    if ($bad) {
        Write-Warning ("$($bad.Count) of $($targets.Count) did not get it. Those " +
                       "PCs still work - Open folder copies the path instead.")
    }
}
