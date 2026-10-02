# ============================================================
#  Order-Agriculture Trust Agent - Environment Check
#  Stack: Huawei Cloud Pangu (LLM) + Huawei Cloud OCR + Vue3
#  Read-only. Prints a report only. Safe to run.
# ============================================================
$ErrorActionPreference = 'SilentlyContinue'

function Test-Tool {
    param([string]$Name, [string]$VersionArg = '--version')
    $c = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $c) { return [pscustomobject]@{ Name = $Name; Status = 'MISSING'; Detail = '' } }
    $detail = ''
    if ($VersionArg) {
        $raw = & $Name $VersionArg 2>&1 | Out-String
        $line = ($raw -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -First 1)
        if ($line) { $detail = $line.Trim() }
    }
    return [pscustomobject]@{ Name = $Name; Status = 'OK'; Detail = $detail }
}

Write-Output ''
Write-Output '########## 1. BASE TOOLCHAIN ##########'
$tools = @(
    @{ n = 'git';    v = '--version' },
    @{ n = 'python'; v = '--version' },
    @{ n = 'py';     v = '--version' },
    @{ n = 'pip';    v = '--version' },
    @{ n = 'node';   v = '--version' },
    @{ n = 'npm';    v = '--version' },
    @{ n = 'pnpm';   v = '--version' },
    @{ n = 'docker'; v = '--version' },
    @{ n = 'code';   v = '--version' },
    @{ n = 'winget'; v = '--version' }
)
foreach ($t in $tools) {
    $r = Test-Tool -Name $t.n -VersionArg $t.v
    Write-Output ("  [{0}] {1,-10} {2}" -f $r.Status.PadRight(7), $r.Name, $r.Detail)
}

Write-Output ''
Write-Output '########## 2. PYTHON ##########'
$pyExe = $null
foreach ($cand in @('python', 'py')) {
    if (Get-Command $cand -ErrorAction SilentlyContinue) { $pyExe = $cand; break }
}
if ($pyExe) {
    $pySrc = (Get-Command $pyExe).Source
    if ($pySrc -like '*WindowsApps*') {
        Write-Output '  WARNING: python resolves to Microsoft Store stub -> real Python NOT installed'
        [void]($script:missingPy = $true)
        $pyExe = $null
    }
}
if ($pyExe) {
    Write-Output ("  exe     : " + (Get-Command $pyExe).Source)
    Write-Output ("  version : " + ((& $pyExe -c "import sys;print(sys.version)" 2>&1 | Out-String).Trim()))
    Write-Output ("  venv    : " + ((& $pyExe -c "import venv;print('available')" 2>&1 | Out-String).Trim()))
    Write-Output ("  pip     : " + ((& $pyExe -m pip --version 2>&1 | Out-String).Trim()))
    Write-Output ("  pip idx : " + ((& $pyExe -m pip config get global.index-url 2>&1 | Out-String).Trim()))
} else {
    Write-Output '  python NOT USABLE'
}

Write-Output ''
Write-Output '########## 3. PYTHON PACKAGES (backend deps) ##########'
if ($pyExe) {
    $pkgs = @(
        'fastapi', 'uvicorn', 'pydantic', 'python-multipart', 'python-dotenv',
        'pymupdf', 'pdfplumber', 'pypdf',
        'httpx', 'requests', 'openai',
        'langchain', 'langgraph', 'sentence-transformers', 'faiss-cpu', 'chromadb',
        'numpy', 'pandas',
        'redis', 'sqlalchemy', 'minio', 'mcp', 'huggingface-hub',
        'paddleocr', 'paddlepaddle', 'pytest'
    )
    $installed = @{}
    foreach ($l in (& $pyExe -m pip list --format=freeze 2>$null)) {
        $p = $l -split '=='
        if ($p.Count -ge 2) { $installed[$p[0].ToLower()] = $p[1] }
    }
    $missPkg = @()
    foreach ($p in $pkgs) {
        if ($installed.ContainsKey($p.ToLower())) {
            Write-Output ("  [OK]      {0,-24} {1}" -f $p, $installed[$p.ToLower()])
        } else {
            Write-Output ("  [MISSING] {0}" -f $p)
            $missPkg += $p
        }
    }
    Write-Output ("  --> missing count: " + $missPkg.Count)
} else {
    Write-Output '  skipped (python not usable)'
}

Write-Output ''
Write-Output '########## 4. NODE / FRONTEND ##########'
if (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Output ("  node     : " + ((& node -v 2>&1 | Out-String).Trim()))
    Write-Output ("  npm      : " + ((& npm -v 2>&1 | Out-String).Trim()))
    Write-Output ("  registry : " + ((& npm config get registry 2>&1 | Out-String).Trim()))
    Write-Output ("  prefix   : " + ((& npm config get prefix 2>&1 | Out-String).Trim()))
} else {
    Write-Output '  node NOT FOUND -> Vue3 frontend cannot build'
}
if (Get-Command pnpm -ErrorAction SilentlyContinue) {
    Write-Output ("  pnpm     : " + ((& pnpm -v 2>&1 | Out-String).Trim()))
} else {
    Write-Output '  pnpm     : not installed (optional)'
}

Write-Output ''
Write-Output '########## 5. DOCKER ENGINE ##########'
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $di = ((& docker info --format '{{.ServerVersion}} | OSType={{.OSType}} | Root={{.DockerRootDir}}' 2>&1 | Out-String).Trim())
    Write-Output ("  docker info: " + $di)
    $dc = ((& docker compose version 2>&1 | Out-String).Trim())
    Write-Output ("  compose v2 : " + $dc)
} else {
    Write-Output '  docker NOT FOUND'
}

Write-Output ''
Write-Output '########## 6. WSL ##########'
$wslOut = ((& wsl.exe --status 2>&1 | Out-String) -replace "`0", "").Trim()
if ($wslOut) { Write-Output ("  " + ($wslOut -replace "`r?`n", ' | ')) } else { Write-Output '  no output (WSL may not be installed)' }

Write-Output ''
Write-Output '########## 7. GPU / CUDA ##########'
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    Write-Output ((& nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>&1 | Out-String).Trim())
} else {
    Write-Output '  no NVIDIA GPU detected -> keep all inference on Huawei Cloud APIs'
}

Write-Output ''
Write-Output '########## 8. WINDOWS PREREQUISITES ##########'
$vc = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64' -ErrorAction SilentlyContinue
if ($vc) {
    Write-Output ("  VC++ 2015-2022 x64 Redist : OK (v" + $vc.Version + ")")
} else {
    Write-Output '  VC++ 2015-2022 x64 Redist : MISSING (needed by some wheels/tools)'
}
$lp = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled
Write-Output ("  LongPathsEnabled          : " + $(if ($lp -eq 1) { '1 (enabled)' } else { '0 (disabled)' }))
$eps = Get-ExecutionPolicy -Scope CurrentUser
Write-Output ("  PS ExecutionPolicy(User)  : " + $eps)

Write-Output ''
Write-Output '########## 9. HUAWEI CLOUD / CREDENTIALS ##########'
$vars = @(
    'HUAWEI_CLOUD_AK', 'HUAWEI_CLOUD_SK', 'HUAWEI_CLOUD_PROJECT_ID', 'HUAWEI_CLOUD_REGION',
    'MODELARTS_API_KEY', 'MAAS_API_KEY', 'PANGU_API_KEY',
    'HUAWEI_OCR_ENDPOINT', 'OPENAI_API_KEY', 'DEEPSEEK_API_KEY', 'DASHSCOPE_API_KEY',
    'ENTERPRISE_API_KEY', 'HF_ENDPOINT', 'HF_HOME', 'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY'
)
foreach ($v in $vars) {
    $val = [Environment]::GetEnvironmentVariable($v, 'Machine')
    if (-not $val) { $val = [Environment]::GetEnvironmentVariable($v, 'User') }
    $state = if ($val) { 'CONFIGURED' } else { 'not set' }
    Write-Output ("  {0,-24} : {1}" -f $v, $state)
}

Write-Output ''
Write-Output '########## 10. NETWORK REACHABILITY ##########'
$urls = @(
    'https://www.huaweicloud.com',
    'https://pypi.org/simple/',
    'https://registry.npmmirror.com',
    'https://hf-mirror.com',
    'https://api.modelarts-maas.com',
    'https://registry-1.docker.io/v2/'
)
foreach ($u in $urls) {
    $ok = $false
    $code = ''
    try {
        $resp = Invoke-WebRequest -Uri $u -Method Head -TimeoutSec 6 -UseBasicParsing -ErrorAction Stop
        $ok = $true; $code = $resp.StatusCode
    } catch {
        if ($_.Exception.Response) { $ok = $true; $code = [int]$_.Exception.Response.StatusCode }
    }
    Write-Output ("  {0,-38} {1}" -f $u, $(if ($ok) { "reachable ($code)" } else { 'UNREACHABLE' }))
}

Write-Output ''
Write-Output '########## 11. DISK ##########'
foreach ($d in (Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free })) {
    Write-Output ("  {0}: free {1} GB" -f $d.Name, [math]::Round($d.Free / 1GB, 1))
}

Write-Output ''
Write-Output '########## DONE ##########'
