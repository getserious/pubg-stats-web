@echo off
setlocal
 title GAME.GG - Keep PC Awake
 echo ======================================================
 echo GAME.GG - Keep PC Awake
 echo ======================================================
 echo Keep this window open or minimized while hosting.
 echo Automatic idle sleep is prevented; the display may turn off.
 echo Close this window or press Ctrl+C to stop.
 echo No administrator rights or permanent power changes required.
 echo This does NOT prevent shutdown, restart, sign-out or lid sleep.
 echo Keep the Flask and Cloudflare windows running separately.
 echo.
 powershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference='Stop'; try { Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class GameggAwake { [DllImport("kernel32.dll", SetLastError=true)] public static extern uint SetThreadExecutionState(uint flags); }'; while ($true) { if ([GameggAwake]::SetThreadExecutionState(1) -eq 0) { throw 'Windows rejected the keep-awake request.' }; Write-Host ('[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] Keep-awake request sent.'); Start-Sleep -Seconds 30 } } catch { Write-Host ('ERROR: ' + $_.Exception.Message); exit 1 }"
 if errorlevel 1 (
 echo.
 echo Keep-awake could not run or was interrupted.
 echo If school policy blocks it, contact the school administrator.
 pause
 )
 endlocal
