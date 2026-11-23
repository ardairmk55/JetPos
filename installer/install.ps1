<#
.SYNOPSIS
  POSHANE yerel sunucu kurulumu (Windows Server / Windows 10-11).
.DESCRIPTION
  Python sanal ortamını kurar, bağımlılıkları yükler, veritabanını hazırlar, statik dosyaları toplar,
  yapılandırma dosyasını (jetpos.env) oluşturur ve isteğe bağlı olarak sunucu + zamanlayıcıyı
  Windows Görev Zamanlayıcı ile açılışta başlatır. İlk kurulum sihirbazı tarayıcıda açılır.
.PARAMETER DatabaseUrl
  PostgreSQL bağlantısı (önerilen): postgres://kullanici:sifre@localhost:5432/jetpos
  Boş bırakılırsa SQLite kullanılır (yalnızca küçük kurulum/deneme).
.PARAMETER Port
  LAN üzerinden dinlenecek port (varsayılan 8000).
.PARAMETER RegisterTasks
  Sunucu ve zamanlayıcıyı Windows açılışında otomatik başlat (yönetici yetkisi gerekir).
.PARAMETER OpenFirewall
  Windows güvenlik duvarında yalnızca özel/etki alanı ağları için port kuralı ekler (yönetici yetkisi gerekir).
.EXAMPLE
  .\install.ps1 -DatabaseUrl "postgres://jetpos:GucluSifre@localhost:5432/jetpos" -RegisterTasks -OpenFirewall
#>
param(
  [string]$DatabaseUrl = "",
  [int]$Port = 8000,
  [string]$DataDir = "",
  [string]$NodeId = $env:COMPUTERNAME,
  [switch]$RegisterTasks,
  [switch]$OpenFirewall,
  [switch]$Demo
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
if (-not $DataDir) { $DataDir = Join-Path $Backend "data" }
$Venv = Join-Path $Root ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }

Step "Python kontrolü"
$sysPy = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $sysPy) { throw "Python 3.12+ bulunamadı. https://www.python.org adresinden kurup tekrar deneyin." }
$ver = & python -c "import sys;print('%d.%d'%sys.version_info[:2])"
if ([version]$ver -lt [version]"3.11") { throw "Python $ver eski; 3.11+ gerekli." }

Step "Sanal ortam ve bağımlılıklar"
if (-not (Test-Path $Py)) { & python -m venv $Venv }
& $Py -m pip install --upgrade pip | Out-Null
& $Py -m pip install -r (Join-Path $Backend "requirements.txt")
try { & $Py -m pip install pywin32 | Out-Null } catch { Write-Warning "pywin32 kurulamadı; Windows sürücülü (USB) yazıcılar devre dışı kalır." }

Step "Yapılandırma (jetpos.env)"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$EnvFile = Join-Path $Root "jetpos.env"
if (-not (Test-Path $EnvFile)) {
  $lines = @(
    "JETPOS_DATA_DIR=$DataDir",
    "JETPOS_NODE_ID=$NodeId",
    "JETPOS_PORT=$Port",
    "JETPOS_ALLOWED_HOSTS=*",
    "JETPOS_TIME_ZONE=Europe/Istanbul"
  )
  if ($DatabaseUrl) { $lines += "DATABASE_URL=$DatabaseUrl" }
  $lines += "# JETPOS_SMTP_HOST=smtp.ornek.com`n# JETPOS_SMTP_PORT=587`n# JETPOS_SMTP_USER=`n# JETPOS_SMTP_PASSWORD=`n# JETPOS_BACKUP_MIRRORS=E:\JETPOS_YEDEK;\\NAS\jetpos`n# JETPOS_CENTRAL_URL=`n# JETPOS_CENTRAL_TOKEN="
  Set-Content -Path $EnvFile -Value $lines -Encoding utf8
  Write-Host "Oluşturuldu: $EnvFile (gizli bilgileri bu dosyada tutun, erişimi kısıtlayın)"
}
Get-Content $EnvFile | Where-Object { $_ -match "^[A-Z_]+=" } | ForEach-Object { $k, $v = $_ -split "=", 2; Set-Item -Path "env:$k" -Value $v }

Step "Veritabanı ve statik dosyalar"
Push-Location $Backend
& $Py manage.py migrate --noinput
& $Py manage.py collectstatic --noinput | Out-Null
if ($Demo) { & $Py manage.py jetpos_demo }
Pop-Location

if ($OpenFirewall) {
  Step "Güvenlik duvarı kuralı (yalnızca özel/etki alanı ağı)"
  if (-not (Get-NetFirewallRule -DisplayName "POSHANE $Port" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "POSHANE $Port" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Private,Domain | Out-Null
  }
}

if ($RegisterTasks) {
  Step "Açılışta otomatik başlatma (Görev Zamanlayıcı)"
  $srv = Join-Path $PSScriptRoot "start_server.ps1"
  $sch = Join-Path $PSScriptRoot "start_scheduler.ps1"
  foreach ($t in @(@("POSHANE Sunucu", $srv), @("POSHANE Zamanlayici", $sch))) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$($t[1])`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $t[0] -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -User "SYSTEM" -Force | Out-Null
    Start-ScheduledTask -TaskName $t[0]
  }
}

$ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } | Select-Object -First 1).IPAddress
Write-Host ""
Write-Host "Kurulum tamamlandı." -ForegroundColor Green
Write-Host "Sunucuyu başlatmak için : installer\start_server.ps1  (RegisterTasks seçtiyseniz otomatik çalışır)"
Write-Host "Yerel ağ adresi         : http://$($ip):$Port   (kasa, garson telefonu ve KDS bu adresi kullanır)"
Write-Host "İlk açılışta kurulum sihirbazı çalışır."
