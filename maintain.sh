#!/bin/bash
# Jetson Orin Nano - System Maintenance Script
set -e

echo "=============================="
echo " Jetson System Maintenance"
echo "=============================="

# 1. APT update + upgrade
echo ""
echo "[1/5] Updating packages..."
apt update
apt upgrade -y
apt autoremove -y
apt clean
echo "  Done."

# 2. Journal logs (keep last 7 days)
echo ""
echo "[2/5] Trimming systemd journal (keeping 7 days)..."
journalctl --vacuum-time=7d
echo "  Done."

# 3. Old crash reports
echo ""
echo "[3/5] Clearing crash reports..."
rm -rf /var/crash/*
echo "  Done."

# 4. Thumbnail & temp cleanup (system-wide)
echo ""
echo "[4/5] Cleaning /tmp and old logs..."
find /tmp -type f -atime +7 -delete 2>/dev/null || true
find /var/log -name "*.gz" -delete 2>/dev/null || true
find /var/log -name "*.1" -delete 2>/dev/null || true
echo "  Done."

# 5. Jetson power mode check
echo ""
echo "[5/5] Jetson power/performance info..."
nvpmodel -q 2>/dev/null || echo "  nvpmodel not found"
jetson_clocks --show 2>/dev/null | head -20 || echo "  jetson_clocks not found"

echo ""
echo "=============================="
echo " Done! Disk usage:"
df -h /
echo "=============================="
