#!/bin/bash
# VPS 初始化脚本
# Usage: bash setup_vps.sh

set -e

echo "=== Polymarket Collector VPS Setup ==="

# 1. System packages
sudo apt update
sudo apt install -y python3.12 python3.12-venv rsync

# 2. Python environment
python3.12 -m venv ~/poly_env
source ~/poly_env/bin/activate

# 3. Install dependencies
pip install --upgrade pip
pip install websockets requests pyyaml

# 4. Create directories
mkdir -p ~/live_data_collector/data
mkdir -p ~/live_data_collector/logs

# 5. Copy project files (run this from your local machine first):
# scp -r src/ config.yaml requirements.txt ubuntu@your-vps:~/live_data_collector/

# 6. Install systemd service
echo "To install as systemd service:"
echo "  sudo cp deploy/polymarket-collector.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable polymarket-collector"
echo "  sudo systemctl start polymarket-collector"
echo ""
echo "To check status:"
echo "  sudo systemctl status polymarket-collector"
echo "  journalctl -u polymarket-collector -f"

echo ""
echo "=== Setup complete ==="
