#!/bin/bash
# 数据同步脚本: VPS -> 本地
# Usage: bash sync_to_local.sh [VPS_HOST] [LOCAL_DIR]
#
# 建议加入 crontab 每小时执行:
# 0 * * * * /home/user/scripts/sync_to_local.sh vps-host /path/to/local/data

VPS_HOST="${1:-ubuntu@your-vps-ip}"
LOCAL_DIR="${2:-D:/quant_trading_workspace/polymarket_data/live}"

echo "$(date '+%Y-%m-%d %H:%M:%S') Syncing from $VPS_HOST..."

rsync -avz --compress \
    --include='*/' \
    --include='*.jsonl.gz' \
    --exclude='*.jsonl' \
    "$VPS_HOST:~/live_data_collector/data/" \
    "$LOCAL_DIR/"

echo "$(date '+%Y-%m-%d %H:%M:%S') Sync complete"
