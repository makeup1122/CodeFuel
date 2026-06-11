# Post hover heartbeats, then dump every top-level window (class/title/visible)
# of the UsageTray python process while the panel should be showing.
$code = @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class WinDump {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int max);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int max);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  public struct RECT { public int L, T, R, B; }
  public static string Dump(uint targetPid) {
    var sb = new StringBuilder();
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid == targetPid) {
        var c = new StringBuilder(256); GetClassNameW(h, c, 256);
        var t = new StringBuilder(256); GetWindowTextW(h, t, 256);
        RECT r; GetWindowRect(h, out r);
        sb.AppendLine(string.Format("{0,10} vis={1,-5} class={2,-40} title='{3}' rect=({4},{5},{6},{7})",
          h, IsWindowVisible(h), c, t, r.L, r.T, r.R, r.B));
      }
      return true;
    }, IntPtr.Zero);
    return sb.ToString();
  }
  public static System.Collections.Generic.List<IntPtr> FindTray(uint targetPid) {
    var list = new System.Collections.Generic.List<IntPtr>();
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid == targetPid) {
        var c = new StringBuilder(256); GetClassNameW(h, c, 256);
        if (c.ToString().EndsWith("SystemTrayIcon")) list.Add(h);
      }
      return true;
    }, IntPtr.Zero);
    return list;
  }
}
'@
Add-Type -TypeDefinition $code
$proc = Get-Process python -ErrorAction SilentlyContinue
if (-not $proc) { Write-Output "no python process"; exit 1 }
$tray = [WinDump]::FindTray([uint32]$proc.Id)
1..5 | ForEach-Object {
  foreach ($w in $tray) { [WinDump]::PostMessageW($w, 0x040B, [IntPtr]::Zero, [IntPtr]0x0200) | Out-Null }
  Start-Sleep -Milliseconds 120
}
Write-Output "--- windows while hovering ---"
Write-Output ([WinDump]::Dump([uint32]$proc.Id))
