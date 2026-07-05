#!/bin/bash
# TaxiBot Systemd Service o'rnatuvchi va avtomatlashtiruvchi skript
# Bu skript botni server reboot bo'lganda ham, crash (xatolik) bo'lganda ham 
# 100% AVTOMATIK qayta ishga tushiradigan qilib sozlaydi.

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
USER="$(whoami)"

echo "[*] Systemd service fayli tayyorlanmoqda..."

cat <<EOF | sudo tee /etc/systemd/system/taxibot.service
[Unit]
Description=TaxiAutoPost Telegram Bot Service
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python3 $DIR/main.py
Restart=always
RestartSec=5
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

echo "[*] Systemd sozlamalari yangilanmoqda va bot ishga tushirilmoqda..."
sudo systemctl daemon-reload
sudo systemctl enable taxibot.service
sudo systemctl restart taxibot.service

echo ""
echo "[+] =================================================================="
echo "[+] TABRIKLAYMIZ! Bot 100% avtomatik boshqaruv tizimiga o'tkazildi!"
echo "[+] =================================================================="
echo "[i] Server reboot bo'lsa ham yoki botda qandaydur xato bo'lib o'chsa ham,"
echo "    tizim uni 5 soniya ichida o'z-o'zidan qayta ishga tushirib ketaveradi."
echo ""
echo "📊 Boshqaruv buyruqlari:"
echo "    • Loglarni jonli ko'rish: sudo journalctl -u taxibot -f"
echo "    • Botni to'xtatish:       sudo systemctl stop taxibot"
echo "    • Qayta ishga tushirish:  sudo systemctl restart taxibot"
echo "    • Holatini tekshirish:    sudo systemctl status taxibot"
echo ""
