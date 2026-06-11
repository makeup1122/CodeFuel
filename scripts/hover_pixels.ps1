# Show the panel via synthetic hover heartbeats, then sample its on-screen
# pixels to verify the WebView actually renders (dark theme) vs blank white.
param([string]$ProcessName = "python")
$code = @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class PixProbe {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int max);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int max);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
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
Add-Type -AssemblyName System.Drawing

$procs = @(Get-Process $ProcessName -ErrorAction SilentlyContinue)
if (-not $procs) { Write-Output "no $ProcessName process"; exit 1 }
foreach ($p in $procs) {
  [PixProbe]::Find([uint32]$p.Id)
  if ([PixProbe]::trayWnds.Count -gt 0) { break }
}
if ([PixProbe]::trayWnds.Count -eq 0) { Write-Output "tray window not found"; exit 1 }

$fgBefore = [PixProbe]::GetForegroundWindow()
# first burst of heartbeats: get the panel shown and positioned
1..4 | ForEach-Object {
  foreach ($w in [PixProbe]::trayWnds) {
    [PixProbe]::PostMessageW($w, 0x040B, [IntPtr]::Zero, [IntPtr]0x0200) | Out-Null
  }
  Start-Sleep -Milliseconds 120
}

$fgAfter = [PixProbe]::GetForegroundWindow()
$stolen = ($fgAfter -ne $fgBefore)
Write-Output "focus stolen by panel: $stolen (fg $fgBefore -> $fgAfter, panel $([PixProbe]::panelWnd))"

$r = New-Object PixProbe+RECT
[PixProbe]::GetWindowRect([PixProbe]::panelWnd, [ref]$r) | Out-Null
$w = $r.R - $r.L; $h = $r.B - $r.T
Write-Output "panel rect: ($($r.L),$($r.T)) ${w}x${h}"
if ($w -le 0 -or $h -le 0) { Write-Output "bad rect"; exit 1 }

# pre-allocate capture objects, then refresh the hover signal and grab the
# pixels immediately so the watchdog cannot hide the panel first
$bmp = New-Object System.Drawing.Bitmap($w, $h)
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
1..2 | ForEach-Object {
  foreach ($w2 in [PixProbe]::trayWnds) {
    [PixProbe]::PostMessageW($w2, 0x040B, [IntPtr]::Zero, [IntPtr]0x0200) | Out-Null
  }
  Start-Sleep -Milliseconds 100
}
# PrintWindow with PW_RENDERFULLCONTENT (2) renders the window's own content
# (incl. WebView2) into the bitmap, independent of z-order/occlusion
$hdc = $gfx.GetHdc()
$ok = [PixProbe]::PrintWindow([PixProbe]::panelWnd, $hdc, 2)
$gfx.ReleaseHdc($hdc)
$gfx.Dispose()
Write-Output "PrintWindow ok=$ok"
$bmp.Save("E:\DashBoard\scripts\panel_capture.png", [System.Drawing.Imaging.ImageFormat]::Png)

# sample a grid of pixels and average
$sumR = 0; $sumG = 0; $sumB = 0; $n = 0
for ($y = 10; $y -lt $h - 10; $y += [Math]::Max(1, [int]($h / 12))) {
  for ($x = 10; $x -lt $w - 10; $x += [Math]::Max(1, [int]($w / 12))) {
    $px = $bmp.GetPixel($x, $y)
    $sumR += $px.R; $sumG += $px.G; $sumB += $px.B; $n++
  }
}
$bmp.Dispose()
Write-Output ("avg color over {0} samples: R={1} G={2} B={3}" -f $n, [int]($sumR/$n), [int]($sumG/$n), [int]($sumB/$n))
Write-Output "capture saved: scripts\panel_capture.png"
