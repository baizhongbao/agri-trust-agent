# ============================================================
#  Docker Hub reachability - detailed probe
#  Read-only. No config changes.
# ============================================================
$ErrorActionPreference = 'SilentlyContinue'

function Test-Tcp {
    param([string]$HostName, [int]$Port = 443, [int]$TimeoutMs = 4000)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect($HostName, $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if ($ok) { $ok = $client.Connected }
        $client.Close()
        return $ok
    } catch { return $false }
}

Write-Output ''
Write-Output '########## A. DNS RESOLUTION ##########'
$hosts = @(
    'registry-1.docker.io',
    'auth.docker.io',
    'production.cloudflare.docker.com',
    'hub.docker.com',
    'swr.cn-north-4.myhuaweicloud.com'
)
foreach ($h in $hosts) {
    $res = Resolve-DnsName -Name $h -Type A -ErrorAction SilentlyContinue
    $ips = (($res | Where-Object { $_.IPAddress } | Select-Object -ExpandProperty IPAddress) -join ', ')
    Write-Output ("  {0,-38} {1}" -f $h, $(if ($ips) { $ips } else { 'DNS FAILED' }))
}

Write-Output ''
Write-Output '########## B. TCP CONNECT :443 ##########'
foreach ($h in $hosts) {
    $r = Test-Tcp -HostName $h
    Write-Output ("  {0,-38} {1}" -f $h, $(if ($r) { 'TCP OK' } else { 'TCP BLOCKED / TIMEOUT' }))
}

Write-Output ''
Write-Output '########## C. HTTP GET /v2/ (Docker Registry API) ##########'
Write-Output '   note: 200 or 401 both mean REACHABLE (401 = registry asking for auth)'
$mirrors = @(
    'https://registry-1.docker.io/v2/',
    'https://docker.m.daocloud.io/v2/',
    'https://docker.nju.edu.cn/v2/',
    'https://docker.mirrors.ustc.edu.cn/v2/',
    'https://docker.1ms.run/v2/',
    'https://hub.rat.dev/v2/',
    'https://dockerpull.org/v2/',
    'https://docker.1panel.live/v2/',
    'https://swr.cn-north-4.myhuaweicloud.com/v2/',
    'https://swr.cn-east-3.myhuaweicloud.com/v2/'
)
foreach ($u in $mirrors) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $code = 'FAIL'
    try {
        $resp = Invoke-WebRequest -Uri $u -Method Get -TimeoutSec 6 -UseBasicParsing -ErrorAction Stop
        $code = [string]$resp.StatusCode
    } catch {
        if ($_.Exception.Response) { $code = [string][int]$_.Exception.Response.StatusCode }
        else { $code = 'FAIL' }
    }
    $sw.Stop()
    $verdict = if ($code -eq '200' -or $code -eq '401') { 'REACHABLE' } else { 'NOT USABLE' }
    Write-Output ("  {0,-50} code={1,-6} {2,6} ms  {3}" -f $u, $code, $sw.ElapsedMilliseconds, $verdict)
}

Write-Output ''
Write-Output '########## D. LOCAL DOCKER STATE ##########'
$daemon = Join-Path $env:USERPROFILE '.docker\daemon.json'
if (Test-Path $daemon) {
    Write-Output ('  daemon.json: ' + $daemon)
    Get-Content $daemon -Raw | ForEach-Object { Write-Output ('    ' + $_) }
} else {
    Write-Output '  daemon.json: NOT FOUND (no mirror configured / Docker not installed)'
}
foreach ($p in @(
        'C:\Program Files\Docker\Docker\Docker Desktop.exe',
        'C:\Program Files\Docker\Docker\resources\bin\docker.exe',
        'C:\ProgramData\DockerDesktop'
    )) {
    Write-Output ("  {0,-58} {1}" -f $p, $(if (Test-Path $p) { 'EXISTS' } else { 'missing' }))
}
$wsl = ((& wsl.exe -l -v 2>&1 | Out-String) -replace "`0", "").Trim()
Write-Output ("  WSL distros: " + $(if ($wsl) { ($wsl -replace "`r?`n", ' | ') } else { 'none / WSL not installed' }))

Write-Output ''
Write-Output '########## DONE ##########'
