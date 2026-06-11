# Posts synthetic tray-icon WM_MOUSEMOVE notifications to the running
# UsageTray instance and reports panel visibility before/after, to verify
# the hover-show + watchdog-hide path end to end.
# Usage: hover_probe.ps1 [-ProcessName python|UsageTray]
param([string]$ProcessName = "python")
$code = @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class TrayProbe {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int max);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int max);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint msg, IntPtr w, IntPtr l);
  public static System.Collections.Generic.List<IntPtr> trayWnds = new System.Collections.Generic.List<IntPtr>();
  public static IntPtr panelWnd = IntPtr.Zero;
  public static void Find(uint targetPid) {
    trayWnds.Clear(); panelWnd = IntPtr.Zero;
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid == targetPid) {
        var c = new StringBuilder(256); GetClassNameW(h, c, 256);
        var t = new StringBuilder(256); GetWindowTextW(h, t, 256);
        // pystray creates _hwnd and _menu_hwnd with the same class; only one
        // is wired to the dispatcher, so report and post to both
        if (c.ToString().EndsWith("SystemTrayIcon")) trayWnds.Add(h);
        if (t.ToString() == "UsageTray") panelWnd = h;
      }
      return true;
    }, IntPtr.Zero);
  }
}
'@
Add-Type -TypeDefinition $code

# PyInstaller onefile runs as bootstrap parent + real child: scan all of them
$procs = @(Get-Process $ProcessName -ErrorAction SilentlyContinue)
if (-not $procs) { Write-Output "no $ProcessName process"; exit 1 }
foreach ($p in $procs) {
  [TrayProbe]::Find([uint32]$p.Id)
  if ([TrayProbe]::trayWnds.Count -gt 0) { break }
}
Write-Output "tray windows: $([TrayProbe]::trayWnds -join ', ')  panel: $([TrayProbe]::panelWnd)"
if ([TrayProbe]::trayWnds.Count -eq 0) { Write-Output "tray window not found"; exit 1 }

Write-Output "visible before: $([TrayProbe]::IsWindowVisible([TrayProbe]::panelWnd))"
# WM_NOTIFY = WM_USER+11 = 0x040B, lParam = WM_MOUSEMOVE (0x0200)
# keep heartbeats flowing (like a real hover) and check WHILE hovering
1..8 | ForEach-Object {
  foreach ($w in [TrayProbe]::trayWnds) {
    [TrayProbe]::PostMessageW($w, 0x040B, [IntPtr]::Zero, [IntPtr]0x0200) | Out-Null
  }
  Start-Sleep -Milliseconds 150
}
Write-Output "visible while hovering: $([TrayProbe]::IsWindowVisible([TrayProbe]::panelWnd))"
# stop heartbeats -> watchdog should hide after the 0.8s grace
Start-Sleep -Seconds 2
Write-Output "visible after leaving: $([TrayProbe]::IsWindowVisible([TrayProbe]::panelWnd))"
