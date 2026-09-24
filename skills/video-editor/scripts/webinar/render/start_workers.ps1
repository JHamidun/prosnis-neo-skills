# S11: start one Remotion render worker (templates/remotion-program/render_worker.mjs) at BelowNormal priority,
# TEMP on the job drive. Several workers share one chunk list: each chunk is claimed with a lock file, finished chunks
# are skipped, so start 2-3 workers with different -Order (asc / desc / mid): they meet in the middle.
# Measured (22 threads, RTX 4090 Laptop): 3 workers x c7 = 44 fps on slides, 4 workers are WORSE (26 fps);
# on a shared machine plan by the first chunk of the real render, not by showcases (G-R6).
#
# Usage:
#   pwsh start_workers.ps1 -Root <job root> -Bundle <bundle dir> -Name A -Conc 7 -Order asc|desc|mid
#        [-Out <job>/render] [-Edls <chunk json> ...] [-LockTag v2] [-Remotion <job>/remotion]
# -LockTag: give a NEW tag after an EDL fix or a new bundle, so fresh workers do not wait on the old workers' locks
#           (old workers finish their current chunk; withdraw chunks rendered from a stale EDL by moving the mp4 away).
# Writes <Out>/worker_<Name>.log/.err and a sidecar worker_<Name>.json (bundle, its mtime, lock tag, start) that
# render/provenance.py uses to prove which EDL and which bundle every chunk was rendered from.
param(
  [Parameter(Mandatory = $true)][string]$Root,
  [Parameter(Mandatory = $true)][string]$Bundle,
  [string]$Name = 'A',
  [int]$Conc = 7,
  [string]$Order = 'asc',
  [string]$Out = '',
  [string[]]$Edls = @(),
  [string]$LockTag = '',
  [string]$Remotion = '',
  [string]$Gl = 'angle'
)
if (-not $Out) { $Out = "$Root/render" }
if (-not $Remotion) { $Remotion = "$Root/remotion" }
New-Item -ItemType Directory -Force -Path $Out, "$Root/tmp" | Out-Null
$env:TEMP = "$Root/tmp"; $env:TMP = "$Root/tmp"; $env:TMPDIR = "$Root/tmp"
$env:GL = $Gl
if ($LockTag) { $env:LOCK_TAG = $LockTag } else { Remove-Item Env:LOCK_TAG -ErrorAction SilentlyContinue }
if ($Edls.Count -eq 0) {
  $all = @(Get-ChildItem "$Root/edl/chunks/full_*.json" | Sort-Object Name | ForEach-Object { $_.FullName })
  switch ($Order) {
    'desc' { [array]::Reverse($all) }
    'mid'  { $h = [int]($all.Count / 2); $all = $all[$h..($all.Count - 1)] + $all[0..($h - 1)] }
  }
  $Edls = $all
}
$argList = @('render_worker.mjs', $Bundle, $Out, "$Conc", $Name) + $Edls
$log = "$Out/worker_$Name.log"
$p = Start-Process -FilePath 'node' -ArgumentList $argList -WorkingDirectory $Remotion -RedirectStandardOutput $log `
  -RedirectStandardError "$Out/worker_$Name.err" -PassThru -WindowStyle Hidden
Start-Sleep -Milliseconds 300
try { $p.PriorityClass = 'BelowNormal' } catch {}
$side = [ordered]@{
  name = $Name; pid = $p.Id; started = (Get-Date).ToString('s'); bundle = $Bundle
  bundle_mtime = (Get-Item $Bundle).LastWriteTime.ToString('s'); lock_tag = $LockTag; concurrency = $Conc; order = $Order; edls = $Edls.Count
}
$side | ConvertTo-Json | Set-Content -Path "$Out/worker_$Name.json" -Encoding utf8
"started worker $Name pid $($p.Id) conc $Conc order $Order edls $($Edls.Count) -> $log"
