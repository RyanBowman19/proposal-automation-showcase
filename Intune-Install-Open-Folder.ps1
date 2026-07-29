<#
    GENERATED FILE - do not edit.
    Built from open-folder.vbs by "Make Intune Script.ps1" on 2026-07-29.
    Edit open-folder.vbs and re-run that instead.

    Intune platform script. Settings that matter:
      Run using logged-on credentials : No   (needs to run as System, for HKLM)
      Enforce script signature check  : No
      Run in 64-bit PowerShell host   : Yes

    Makes the VS Search "Open folder" button open Explorer on this machine,
    for every user of it. Users are never asked to do anything.
#>
$ErrorActionPreference = 'Stop'

$installDir  = Join-Path $env:ProgramData 'VS Search'
$helperPath  = Join-Path $installDir 'open-folder.vbs'
$protocolKey = 'HKLM:\SOFTWARE\Classes\vsfolder'

$helper = @'
' Opens Explorer for an "Open folder" click on the VS Search page.
'
' Enable Open Folder.bat registers this script as the handler for vsfolder:
' links, so Windows hands us the whole link as one argument, like:
'   vsfolder:%5C%5CFILESERVER%5C...%5CSample%20Project.docx
'
' We decode that back into a real path and show it in Explorer. Anything that
' is not a file or folder already sitting on this PC's drives is refused -
' this must never turn into a way for a web page to start a program.
'
' Known limit: plain %XX decoding, so a path with accented or non-English
' characters in it won't be found. Use Copy path on the page for those.

Option Explicit

Dim args, link, target, fso, shell

Set args = WScript.Arguments
If args.Count = 0 Then WScript.Quit 1
link = args(0)

If LCase(Left(link, 9)) = "vsfolder:" Then link = Mid(link, 10)
' Some browsers add slashes of their own after the colon.
Do While Left(link, 1) = "/"
  link = Mid(link, 2)
Loop

target = UrlDecode(link)
' A trailing slash would stop FolderExists finding it.
Do While Len(target) > 3 And (Right(target, 1) = "/" Or Right(target, 1) = "\")
  target = Left(target, Len(target) - 1)
Loop

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

If fso.FileExists(target) Then
  ' Same as the host PC does: show the file sitting in its folder, rather
  ' than opening it - the source documents must never be edited.
  ' The space after "/select," matters. Without it Explorer gives up on the
  ' back half of a path containing "&" and opens the folder above instead
  ' (tested on \...\3 - LPA\STUDIES & PER\, which landed on 3 - LPA).
  shell.Run "explorer.exe /select, """ & target & """", 1, False
ElseIf fso.FolderExists(target) Then
  shell.Run "explorer.exe """ & target & """", 1, False
Else
  MsgBox "This computer can't get to:" & vbCrLf & vbCrLf & target & vbCrLf & vbCrLf & _
    "You probably need the network drives mapped, or the VPN if you're " & _
    "working from home.", 48, "VS Search"
  WScript.Quit 1
End If

Function UrlDecode(s)
  Dim i, c, out
  out = ""
  i = 1
  Do While i <= Len(s)
    c = Mid(s, i, 1)
    If c = "%" And i + 2 <= Len(s) And IsHex(Mid(s, i + 1, 2)) Then
      out = out & Chr(CLng("&H" & Mid(s, i + 1, 2)))
      i = i + 3
    Else
      out = out & c
      i = i + 1
    End If
  Loop
  UrlDecode = out
End Function

Function IsHex(pair)
  Dim i, c
  IsHex = False
  If Len(pair) <> 2 Then Exit Function
  For i = 1 To 2
    c = LCase(Mid(pair, i, 1))
    If InStr("0123456789abcdef", c) = 0 Then Exit Function
  Next
  IsHex = True
End Function

'@

try {
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    Set-Content -Path $helperPath -Value $helper -Encoding ASCII

    New-Item -Path $protocolKey -Force | Out-Null
    Set-ItemProperty -Path $protocolKey -Name '(default)'    -Value 'URL:VS Search folder'
    Set-ItemProperty -Path $protocolKey -Name 'URL Protocol' -Value ''

    $commandKey = Join-Path $protocolKey 'shell\open\command'
    New-Item -Path $commandKey -Force | Out-Null
    Set-ItemProperty -Path $commandKey -Name '(default)' `
        -Value ('wscript.exe "{0}" "%1"' -f $helperPath)

    if (-not ((Test-Path $helperPath) -and (Test-Path $commandKey))) {
        Write-Error 'Registry key or helper file missing after install.'
        exit 1
    }

    Write-Output "Open folder installed for all users of $env:COMPUTERNAME."
    exit 0
}
catch {
    # Intune reads the exit code, so fail loudly rather than silently.
    Write-Error $_.Exception.Message
    exit 1
}
