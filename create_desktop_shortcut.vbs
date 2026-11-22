' Creates a Desktop Shortcut for PredatorSync.exe
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
strDesktop = WshShell.SpecialFolders("Desktop")

strTarget = WshShell.CurrentDirectory & "\dist\PredatorSync.exe"
If Not FSO.FileExists(strTarget) Then
    strTarget = WshShell.CurrentDirectory & "\dist\PredatorSync\PredatorSync.exe"
End If

Set oShortcut = WshShell.CreateShortcut(strDesktop & "\Predator Keyboard Sync.lnk")
oShortcut.TargetPath = strTarget
oShortcut.WorkingDirectory = FSO.GetParentFolderName(strTarget)
strIcon = WshShell.CurrentDirectory & "\assets\predator_icon.ico"
If FSO.FileExists(strIcon) Then
    oShortcut.IconLocation = strIcon & ", 0"
End If
oShortcut.Description = "Acer Predator Helios Neo 16 4-Zone RGB Music Sync"
oShortcut.Save
Set oShortcut = Nothing
Set FSO = Nothing
Set WshShell = Nothing
MsgBox "Desktop shortcut created successfully for Predator Keyboard Sync!", 64, "Predator Sync"
