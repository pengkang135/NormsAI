' Norms-AI silent launcher (no console window).
'
' Content is intentionally ASCII-only: VBScript is read as ANSI/GBK by wscript,
' so UTF-8 Chinese in this file breaks parsing with a syntax error.
' Chinese-language logging lives in silent-start.ps1, which is UTF-8 with BOM.
'
' PowerShell's -WindowStyle Hidden still flashes a console on autostart;
' WScript.Shell Run(cmd, 0, False) is the only fully invisible way.
'
' Usage: double-click, or register via install-autostart.ps1

Option Explicit

Dim shell, fso, scriptDir, ps1Path, cmd

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
ps1Path = fso.BuildPath(scriptDir, "silent-start.ps1")

If Not fso.FileExists(ps1Path) Then
    ' Only case where we interrupt the user: the launcher itself is broken.
    MsgBox "silent-start.ps1 not found:" & vbCrLf & ps1Path, vbCritical, "Norms-AI startup failed"
    WScript.Quit 1
End If

cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1Path & """"

' 0 = hidden window, False = do not wait
shell.Run cmd, 0, False
