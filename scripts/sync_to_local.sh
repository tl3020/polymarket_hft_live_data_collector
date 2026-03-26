#!/bin/bash
# 数据同步脚本: VPS -> 本地
# Usage: bash sync_to_local.sh [VPS_HOST] [LOCAL_DIR]
#
# 建议加入 crontab 每小时执行:
# 0 * * * * /home/user/scripts/sync_to_local.sh vps-host /path/to/local/data

VPS_HOST="${1:-root@45.152.65.16}"
VPS_PORT="${2:-57777}"
LOCAL_DIR="${3:-D:/quant_trading_workspace/polymarket_data/live}"
REMOTE_DATA="/usr/local/application/polymarket-hft-live-data-collector/data"

echo "$(date '+%Y-%m-%d %H:%M:%S') Syncing from $VPS_HOST:$VPS_PORT..."

rsync -avz --compress \
    -e "ssh -p $VPS_PORT" \
    --include='*/' \
    --include='*.jsonl.gz' \
    --exclude='*.jsonl' \
    "$VPS_HOST:$REMOTE_DATA/" \
    "$LOCAL_DIR/"

echo "$(date '+%Y-%m-%d %H:%M:%S') Sync complete"
