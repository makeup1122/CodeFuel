# End-to-end flicker test:
# 1) show the panel via synthetic hover heartbeats
# 2) park the REAL cursor inside the panel rect, stop heartbeats
#    -> panel must stay visible with zero visibility flips (no flicker)
# 3) move the cursor far away -> panel must hide after ~2s linger
param([string]$ProcessName = "python")
$code = @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class FlickProbe {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int max);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int max);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  public struct RECT { public int L, T, R, B; }
  public static System.Collections.Generic.List<IntPtr> trayWnds = new System.Collections.Generic.List<IntPtr>();
  public static IntPtr panelWnd = IntPtr.Zero;
  public static void Find(uint targetPid) {
    trayWnds.Clear(); panelWnd = IntPtr.Zero;
    EnumWindows((h, l) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid == targetPid) {
        var c = new StringBuilder(256); GetClassNameW(h, c, 256);
        var t = new StringBuilder(256); GetWindowTextW(h, t, 256);
        if (c.ToString().EndsWith("SystemTrayIcon")) trayWnds.Add(h);
        if (t.ToString() == "UsageTray") panelWnd = h;
      }
      return true;
    }, IntPtr.Zero);
  }
}
'@
Add-Type -TypeDefinition $code

$procs = @(Get-Process $ProcessName -ErrorAction SilentlyContinue)
if (-not $procs) { Write-Output "no $ProcessName process"; exit 1 }
foreach ($p in $procs) {
  [FlickProbe]::Find([uint32]$p.Id)
  if ([FlickProbe]::trayWnds.Count -gt 0) { break }
}
if ([FlickProbe]::trayWnds.Count -eq 0) { Write-Output "tray window not found"; exit 1 }

# 1) show panel
1..4 | ForEach-Object {
  foreach ($w in [FlickProbe]::trayWnds) {
    [FlickProbe]::PostMessageW($w, 0x040B, [IntPtr]::Zero, [IntPtr]0x0200) | Out-Null
  }
  Start-Sleep -Milliseconds 120
}
if (-not [FlickProbe]::IsWindowVisible([FlickProbe]::panelWnd)) { Write-Output "panel did not show"; exit 1 }

# 2) park real cursor inside the panel, stop heartbeats, watch for flicker
$r = New-Object FlickProbe+RECT
[FlickProbe]::GetWindowRect([FlickProbe]::panelWnd, [ref]$r) | Out-Null
$cx = [int](($r.L + $r.R) / 2); $cy = [int](($r.T + $r.B) / 2)
[FlickProbe]::SetCursorPos($cx, $cy) | Out-Null
Write-Output "cursor parked at ($cx,$cy) inside panel rect ($($r.L),$($r.T),$($r.R),$($r.B))"

$flips = 0; $visSamples = 0; $total = 0
$prev = $true
1..30 | ForEach-Object {
  Start-Sleep -Milliseconds 100
  $v = [FlickProbe]::IsWindowVisible([FlickProbe]::panelWnd)
  $total++
  if ($v) { $visSamples++ }
  if ($v -ne $prev) { $flips++ }
  $prev = $v
}
Write-Output "rest 3s: visible $visSamples/$total samples, flips=$flips"

# 3) move cursor far away, measure linger until hide
[FlickProbe]::SetCursorPos(200, 200) | Out-Null
$t0 = [Diagnostics.Stopwatch]::StartNew()
while ([FlickProbe]::IsWindowVisible([FlickProbe]::panelWnd) -and $t0.Elapsed.TotalSeconds -lt 6) {
  Start-Sleep -Milliseconds 50
}
$hidden = -not [FlickProbe]::IsWindowVisible([FlickProbe]::panelWnd)
Write-Output ("after leaving: hidden={0} linger={1:N2}s" -f $hidden, $t0.Elapsed.TotalSeconds)
