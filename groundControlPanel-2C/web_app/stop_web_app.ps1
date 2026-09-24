[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$appDirectory = (Resolve-Path -LiteralPath $PSScriptRoot).Path.TrimEnd("\")
$frontendDirectory = Join-Path $appDirectory "frontend"
$runScript = Join-Path $appDirectory "run.py"
$instanceLock = Join-Path $appDirectory ".web_app.lock"
$knownTcpPorts = @(8765, 8766, 5173)
$knownUdpPorts = @(56999, 56998)

$instanceMetadata = $null
if (Test-Path -LiteralPath $instanceLock -PathType Leaf) {
    try {
        $lockStream = [System.IO.File]::Open(
            $instanceLock,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::ReadWrite
        )
        try {
            [void]$lockStream.Seek(1, [System.IO.SeekOrigin]::Begin)
            $lockReader = [System.IO.StreamReader]::new(
                $lockStream,
                [System.Text.Encoding]::UTF8,
                $false,
                1024,
                $true
            )
            try {
                $lockText = $lockReader.ReadToEnd()
            }
            finally {
                $lockReader.Dispose()
            }
        }
        finally {
            $lockStream.Dispose()
        }
        if (-not [string]::IsNullOrWhiteSpace($lockText)) {
            $instanceMetadata = $lockText | ConvertFrom-Json
        }
    }
    catch {
        Write-Warning "[GCS] Could not read the instance lock; force-stop fallback remains available."
    }
}

$endpointProcessIds = [System.Collections.Generic.HashSet[int]]::new()
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in $knownTcpPorts } |
    ForEach-Object { [void]$endpointProcessIds.Add([int]$_.OwningProcess) }
Get-NetUDPEndpoint -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in $knownUdpPorts } |
    ForEach-Object { [void]$endpointProcessIds.Add([int]$_.OwningProcess) }

$absoluteRunPattern = [regex]::Escape($runScript)
$frontendPattern = [regex]::Escape($frontendDirectory)
$relativeRunPattern = '(?i)(^|[\s"''])(?:[.]?[\\/])?run[.]py(?=$|[\s"''])'
$targets = @(
    Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object {
            $name = [string]$_.Name
            $commandLine = [string]$_.CommandLine
            $processId = [int]$_.ProcessId
            $isPython = $name -match '^(?i)python(?:w)?[.]exe$'
            $isNode = $name -match '^(?i)node[.]exe$'
            $isExactRun = $isPython -and $commandLine -match $absoluteRunPattern
            $isKnownRunListener = (
                $isPython -and
                $endpointProcessIds.Contains($processId) -and
                $commandLine -match $relativeRunPattern
            )
            $isFrontendDevServer = (
                $isNode -and
                $commandLine -match $frontendPattern -and
                $commandLine -match '(?i)(vite|playwright)'
            )
            $isExactRun -or $isKnownRunListener -or $isFrontendDevServer
        } |
        Sort-Object ProcessId -Unique
)

if (-not $targets) {
    Write-Host "[GCS] No GroundControlPanel Web backend or development server is running."
    Write-Host "[GCS] Browser processes were intentionally left untouched."
    exit 0
}

$failed = $false
foreach ($target in $targets) {
    $processId = [int]$target.ProcessId
    Write-Host "[GCS] Stopping $($target.Name) PID $processId"
    try {
        $isLockedBackend = (
            $null -ne $instanceMetadata -and
            [string]$instanceMetadata.application -eq "GroundControlPanel-2C/web_app" -and
            [int]$instanceMetadata.pid -eq $processId -and
            -not [string]::IsNullOrWhiteSpace([string]$instanceMetadata.shutdown_token)
        )
        if ($isLockedBackend) {
            $shutdownUri = "http://127.0.0.1:$([int]$instanceMetadata.port)/api/runtime/shutdown"
            try {
                $shutdownRequest = @{
                    Uri = $shutdownUri
                    Method = "Post"
                    Headers = @{
                        "X-GCS-Shutdown-Token" = [string]$instanceMetadata.shutdown_token
                    }
                    TimeoutSec = 2
                }
                Invoke-RestMethod @shutdownRequest | Out-Null
                Wait-Process -Id $processId -Timeout 8 -ErrorAction SilentlyContinue
            }
            catch {
                Write-Warning "[GCS] Graceful shutdown was unavailable; using process-stop fallback."
            }
        }
        if ($null -eq (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
            Write-Host "[GCS] PID $processId stopped cleanly."
            continue
        }
        Stop-Process -Id $processId -ErrorAction Stop
        Wait-Process -Id $processId -Timeout 5 -ErrorAction SilentlyContinue
    }
    catch {
        $failed = $true
        Write-Error "[GCS] Failed to stop PID ${processId}: $($_.Exception.Message)"
    }
}

if ($failed) {
    exit 1
}

Write-Host "[GCS] GroundControlPanel Web processes have been stopped."
Write-Host "[GCS] Browser processes were intentionally left untouched."
