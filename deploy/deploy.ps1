<#
NOC-Wanddisplay – von Windows per SSH auf den Raspberry Pi übertragen und einrichten.
Benötigt die in Windows 10/11 enthaltenen Programme ssh, scp und tar.

  .\deploy\deploy.ps1 -Target pi@noc-display.local
  .\deploy\deploy.ps1 -Target pi@192.168.1.50 -Reset -Reboot -Hostname noc-display
#>
param(
  [Parameter(Mandatory = $true)][string]$Target,
  [switch]$Reset,
  [switch]$Reboot,
  [string]$Hostname = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Archive = Join-Path $env:TEMP "noc-dashboard.tar.gz"

if (-not (Test-Path (Join-Path $Root "config\config.env"))) {
  Write-Host "Hinweis: config\config.env fehlt – auf dem Pi bleibt die vorhandene Konfiguration (oder Demo-Modus)."
}
if (-not (Get-ChildItem (Join-Path $Root "sounds") -Filter *.wav -ErrorAction SilentlyContinue)) {
  Write-Host "Hinweis: keine .wav-Datei in sounds\ – Alarmton bleibt stumm."
}

Write-Host "==> Packe Dateien"
tar -C $Root --exclude=__pycache__ -czf $Archive app web deploy config sounds
if ($LASTEXITCODE -ne 0) { throw "tar fehlgeschlagen" }

Write-Host "==> Übertrage nach $Target"
scp -q $Archive "${Target}:/tmp/noc-dashboard.tar.gz"
if ($LASTEXITCODE -ne 0) { throw "scp fehlgeschlagen" }

$opts = @()
if ($Reset) { $opts += "--reset" }
if ($Hostname) { $opts += "--hostname"; $opts += $Hostname }
$installArgs = $opts -join " "

Write-Host "==> Installiere auf dem Pi"
# Windows-Zeilenenden in den Skripten entfernen, falls Git sie umgewandelt hat
$remote = "set -e; rm -rf /tmp/noc-dashboard-src; mkdir -p /tmp/noc-dashboard-src; " +
  "tar -xzf /tmp/noc-dashboard.tar.gz -C /tmp/noc-dashboard-src; " +
  "find /tmp/noc-dashboard-src -type f \( -name '*.sh' -o -name '*.service' -o -name '*.env' -o -name '*.py' \) -exec sed -i 's/\r$//' {} +; " +
  "sudo bash /tmp/noc-dashboard-src/deploy/install.sh $installArgs; " +
  "rm -rf /tmp/noc-dashboard-src /tmp/noc-dashboard.tar.gz"
ssh -t $Target $remote
if ($LASTEXITCODE -ne 0) { throw "Installation fehlgeschlagen" }
Remove-Item $Archive -ErrorAction SilentlyContinue

if ($Reboot) {
  Write-Host "==> Starte Pi neu"
  ssh $Target "sudo systemctl reboot"
}
