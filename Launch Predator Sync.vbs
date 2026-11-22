' Predator Keyboard Music Sync - Silent Windows Launcher
' Launches the app invisibly with pythonw (no black CMD terminal window)

Set WshShell = CreateObject("WScript.Shell")
strPath = WshShell.CurrentDirectory
WshShell.Run "pythonw """ & strPath & "\run_app.pyw""", 0, False
Set WshShell = Nothing
