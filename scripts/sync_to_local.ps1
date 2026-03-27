# sync_to_local.ps1 - VPS -> Local data sync (Windows PowerShell)
# Only syncs completed .jsonl.gz files (skips active .jsonl being written)
#
# Usage:
#   .\sync_to_local.ps1              # one-time sync
#   .\sync_to_local.ps1 -Loop        # loop every hour
#   .\sync_to_local.ps1 -Loop -IntervalMin 30  # loop every 30 min

param(
    [switch]$Loop,
    [int]$IntervalMin = 60
)

$VPS_HOST = "polymarket-vps"
$REMOTE_DATA = "/usr/local/application/polymarket-hft-live-data-collector/data"
$LOCAL_DATA = "D:\quant_trading_workspace\polymarket_data\live\data"
$LOG_DIR = "D:\quant_trading_workspace\polymarket_data\live\.logs"

# Ensure directories exist
if (-not (Test-Path $LOCAL_DATA)) { New-Item -ItemType Directory -Path $LOCAL_DATA -Force | Out-Null }
if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null }

$logFile = Join-Path $LOG_DIR "sync_$(Get-Date -Format 'yyyy-MM-dd').log"

function Write-Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

function Sync-Data {
    Write-Log "=== Start sync ==="

    # Get list of .gz files from server
    $remoteFiles = ssh -o ConnectTimeout=10 -o BatchMode=yes $VPS_HOST "find $REMOTE_DATA -name '*.jsonl.gz' -type f" 2>&1

    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR: SSH connection failed - $remoteFiles"
        return $false
    }

    $files = $remoteFiles -split "`n" | Where-Object { $_.Trim() -ne "" }
    Write-Log "Server has $($files.Count) gz files"

    $downloaded = 0
    $skipped = 0

    foreach ($remotePath in $files) {
        $remotePath = $remotePath.Trim()
        if ($remotePath -eq "") { continue }

        # Convert remote path to local path
        $relPath = $remotePath.Replace("$REMOTE_DATA/", "").Replace("/", "\")
        $localPath = Join-Path $LOCAL_DATA $relPath

        # Skip existing files
        if (Test-Path $localPath) {
            $skipped++
            continue
        }

        # Create local directory
        $localDir = Split-Path $localPath -Parent
        if (-not (Test-Path $localDir)) {
            New-Item -ItemType Directory -Path $localDir -Force | Out-Null
        }

        # Download
        scp -o ConnectTimeout=10 -o BatchMode=yes "${VPS_HOST}:${remotePath}" $localPath 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $downloaded++
        } else {
            Write-Log "  FAIL: $relPath"
        }
    }

    Write-Log "Sync done: downloaded $downloaded, skipped $skipped (already exist)"
    return $true
}

# Execute
if ($Loop) {
    Write-Log "Starting loop mode (every ${IntervalMin} min)"
    while ($true) {
        Sync-Data
        Write-Log "Next sync at: $(Get-Date ((Get-Date).AddMinutes($IntervalMin)) -Format 'HH:mm:ss')"
        Start-Sleep -Seconds ($IntervalMin * 60)
    }
} else {
    Sync-Data
}
