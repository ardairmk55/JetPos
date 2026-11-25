<# :
@echo off
chcp 65001 >nul
title POSHANE Yazici Koprusu
set "POSHANE_SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "iex (Get-Content -LiteralPath $env:POSHANE_SELF -Raw -Encoding UTF8)"
pause
exit /b
#>
# POSHANE Yazıcı Köprüsü: sunucudaki baskı işlerini HTTPS ile çeker, restorandaki yazıcıya yollar.
# Dışarıdan bağlantı kabul etmez; modemde port açmak gerekmez.
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Server = '__SERVER_URL__'
$AppDir = if ($env:POSHANE_AGENT_HOME) { $env:POSHANE_AGENT_HOME } else { Join-Path $env:LOCALAPPDATA 'POSHANE' }
$TokenFile = Join-Path $AppDir 'anahtar.txt'
$IsTest = [bool]$env:POSHANE_AGENT_HOME

function Write-Log($text) { Write-Host ('{0:HH:mm:ss}  {1}' -f (Get-Date), $text) }

$uri = [Uri]$Server
if ($uri.Scheme -ne 'https' -and @('localhost', '127.0.0.1', 'testserver') -notcontains $uri.Host) {
    Write-Log "Güvenlik: sunucu adresi https olmalı ($Server)."
    return
}

$mutex = New-Object System.Threading.Mutex($false, "POSHANE-Yazici-Koprusu$(if ($IsTest) { '-test' })")
if (-not $mutex.WaitOne(0)) { Write-Log 'Köprü zaten açık. Bu pencereyi kapatabilirsiniz.'; return }

Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class PoshaneRawPrinter {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public class DocInfo { public string Name; public string OutputFile; public string DataType; }

    [DllImport("winspool.drv", EntryPoint = "OpenPrinterW", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool OpenPrinter(string name, out IntPtr handle, IntPtr defaults);
    [DllImport("winspool.drv", EntryPoint = "StartDocPrinterW", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern int StartDocPrinter(IntPtr handle, int level, [In] DocInfo info);
    [DllImport("winspool.drv", SetLastError = true)] static extern bool StartPagePrinter(IntPtr handle);
    [DllImport("winspool.drv", SetLastError = true)] static extern bool WritePrinter(IntPtr handle, byte[] data, int count, out int written);
    [DllImport("winspool.drv", SetLastError = true)] static extern bool EndPagePrinter(IntPtr handle);
    [DllImport("winspool.drv", SetLastError = true)] static extern bool EndDocPrinter(IntPtr handle);
    [DllImport("winspool.drv")] static extern bool ClosePrinter(IntPtr handle);

    static void Check(bool ok) { if (!ok) throw new Win32Exception(Marshal.GetLastWin32Error()); }

    public static void Send(string printer, byte[] data) {
        IntPtr h;
        Check(OpenPrinter(printer, out h, IntPtr.Zero));
        try {
            Check(StartDocPrinter(h, 1, new DocInfo { Name = "POSHANE", DataType = "RAW" }) != 0);
            try {
                Check(StartPagePrinter(h));
                int written;
                Check(WritePrinter(h, data, data.Length, out written));
                Check(written == data.Length);
                Check(EndPagePrinter(h));
            } finally { EndDocPrinter(h); }
        } finally { ClosePrinter(h); }
    }
}
'@

function Send-Network($address, $port, [byte[]]$data) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connect = $client.BeginConnect($address, $port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(5000)) { throw 'bağlantı zaman aşımına uğradı' }
        $client.EndConnect($connect)
        $client.SendTimeout = 5000
        $stream = $client.GetStream()
        $stream.Write($data, 0, $data.Length)
        $stream.Flush()
    } finally { $client.Close() }
}

function Invoke-Job($job) {
    $data = [Convert]::FromBase64String($job.data)
    if ($job.connection -eq 'network') {
        try { Send-Network $job.address ([int]$job.port) $data }
        catch { throw "Ağ yazıcısına bağlanılamadı ($($job.address):$($job.port)): $($_.Exception.GetBaseException().Message)" }
    } elseif ($job.connection -eq 'windows') {
        try { [PoshaneRawPrinter]::Send($job.address, $data) }
        catch {
            $reason = $_.Exception.GetBaseException().Message
            $names = try { (Get-Printer | ForEach-Object { $_.Name }) -join ', ' } catch { '' }
            throw "Windows yazıcı hatası ($($job.address)): $reason Bu bilgisayardaki yazıcılar: $names"
        }
    } else { throw "Desteklenmeyen bağlantı türü: $($job.connection)" }
}

function Invoke-Api($path, $token, $body) {
    $web = New-Object System.Net.WebClient
    $web.Encoding = [Text.Encoding]::UTF8
    $web.Headers.Add('Authorization', "Bearer $token")
    $web.Headers.Add('Content-Type', 'application/json; charset=utf-8')
    try { $web.UploadString("$Server/api/print-agent/$path", 'POST', (ConvertTo-Json $body -Compress)) | ConvertFrom-Json }
    finally { $web.Dispose() }
}

function Get-StatusCode($err) {
    $e = $err.Exception
    while ($e -and -not ($e -is [Net.WebException])) { $e = $e.InnerException }
    if ($e -and $e.Response) { return [int]$e.Response.StatusCode }
    return 0
}

function Read-SavedToken {
    if ($env:POSHANE_AGENT_TOKEN) { return $env:POSHANE_AGENT_TOKEN }
    if (-not (Test-Path -LiteralPath $TokenFile)) { return $null }
    try {
        # Anahtar Windows kullanıcı hesabına bağlı olarak şifreli saklanır (DPAPI).
        $secure = ConvertTo-SecureString ((Get-Content -LiteralPath $TokenFile -Raw).Trim())
        return (New-Object Net.NetworkCredential('', $secure)).Password
    } catch { return $null }
}

function Request-Token {
    while ($true) {
        $typed = (Read-Host 'POSHANE > Yazıcılar sayfasındaki köprü anahtarını yapıştırıp Enter''a basın').Trim()
        if (-not $typed) { continue }
        try { Invoke-Api 'result' $typed @{ job = 0 } | Out-Null }
        catch {
            $code = Get-StatusCode $_
            if ($code -eq 401) { Write-Log 'Anahtar yanlış. Tekrar deneyin.'; continue }
            # Geçerli anahtar + olmayan iş = 404
            if ($code -ne 404) { Write-Log "Sunucuya ulaşılamadı: $($_.Exception.Message)"; continue }
        }
        New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
        ConvertTo-SecureString $typed -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -LiteralPath $TokenFile
        return $typed
    }
}

function Install-Autostart {
    try {
        New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
        $copy = Join-Path $AppDir 'POSHANE-Yazici-Koprusu.cmd'
        if ($env:POSHANE_SELF -and $env:POSHANE_SELF -ne $copy) { Copy-Item -LiteralPath $env:POSHANE_SELF -Destination $copy -Force }
        $link = Join-Path ([Environment]::GetFolderPath('Startup')) 'POSHANE Yazici Koprusu.lnk'
        $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
        $shortcut.TargetPath = $copy
        $shortcut.WindowStyle = 7   # simge durumunda başlar
        $shortcut.Save()
        Write-Log 'Bilgisayar açılınca köprü kendiliğinden başlayacak.'
    } catch { Write-Log "Otomatik başlatma kurulamadı: $($_.Exception.Message)" }
}

$token = Read-SavedToken
if (-not $token) { $token = Request-Token }
if (-not $IsTest) { Install-Autostart }
Write-Log "Köprü çalışıyor ($Server). Bu pencereyi KAPATMAYIN; simge durumuna küçültebilirsiniz."

$printed = @{}   # basılıp sunucuya bildirilemeyen iş tekrar gelirse ikinci kez basılmaz
$offline = $false
while ($true) {
    $delay = 3
    $job = $null
    try {
        $job = (Invoke-Api 'claim' $token @{}).job
        if ($offline) { Write-Log 'Sunucu bağlantısı geri geldi.'; $offline = $false }
        if ($job) {
            $key = "$($job.id):$($job.data.GetHashCode())"
            $result = @{ job = $job.id; ok = $true; error = '' }
            if (-not $printed.ContainsKey($key)) {
                try {
                    Invoke-Job $job
                    $printed[$key] = $true
                    Write-Log "Basıldı: $($job.title) ($($job.printer))"
                } catch {
                    $result.ok = $false
                    $result.error = $_.Exception.Message
                    Write-Log "BASILAMADI: $($result.error)"
                }
            }
            Invoke-Api 'result' $token $result | Out-Null
            if ($result.ok) { $delay = 0 }
        }
    } catch {
        if ((Get-StatusCode $_) -eq 401) {
            Write-Log 'Anahtar artık geçerli değil (sitede yeni anahtar üretilmiş olabilir).'
            if ($env:POSHANE_AGENT_TOKEN) { return }
            $token = Request-Token
        } else {
            if (-not $offline) { Write-Log "Sunucuya ulaşılamıyor, denemeye devam ediliyor: $($_.Exception.Message)"; $offline = $true }
            $delay = 10
        }
    }
    # Testlerde: kuyruk boşalınca çık.
    if ($env:POSHANE_AGENT_ONCE -and -not $job) { return }
    Start-Sleep -Seconds $delay
}
