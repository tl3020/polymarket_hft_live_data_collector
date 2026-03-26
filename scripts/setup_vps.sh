#!/bin/bash
# VPS 初始化脚本
# Usage: bash setup_vps.sh
# 假设代码已通过 git clone 到 /usr/local/application/polymarket-hft-live-data-collector/

set -e

PROJECT_DIR="/usr/local/application/polymarket-hft-live-data-collector"

echo "=== Polymarket Collector VPS Setup ==="

# 1. System packages
apt update
apt install -y python3 python3-venv rsync

# 2. Python venv
cd "$PROJECT_DIR"
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Create data directory
mkdir -p "$PROJECT_DIR/data"

# 5. Install systemd service
cp deploy/polymarket-collector.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable polymarket-collector

echo ""
echo "=== Setup complete ==="
echo ""
echo "测试运行 (前台，用 config_test.yaml 只采集 BTC 1H):"
echo "  cd $PROJECT_DIR && source .venv/bin/activate"
echo "  python -m src.main -c config_test.yaml"
echo ""
echo "正式运行 (systemd):"
echo "  systemctl start polymarket-collector"
echo "  journalctl -u polymarket-collector -f"
