#!/bin/bash
set -e

APP_DIR="/opt/sniper-bot"
SERVICE_NAME="sniper-bot"

echo "=== Installing system dependencies ==="
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git

echo "=== Creating app directory ==="
sudo mkdir -p "$APP_DIR"
sudo chown "$USER:$USER" "$APP_DIR"

echo "=== Copying bot files ==="
rsync -av --exclude='.venv' --exclude='data/' --exclude='__pycache__' \
    --exclude='.env' --exclude='*.pyc' --exclude='.stop' \
    "$(dirname "$0")/../" "$APP_DIR/"

echo "=== Creating virtual environment ==="
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "=== Setting up data directory ==="
mkdir -p "$APP_DIR/data"

echo "=== Creating .env ==="
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env" 2>/dev/null || true
    echo ""
    echo "!!! IMPORTANT: Edit $APP_DIR/.env with your keys !!!"
    echo "    nano $APP_DIR/.env"
    echo ""
fi

echo "=== Installing systemd service ==="
sudo cp "$APP_DIR/deploy/sniper-bot.service" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo sed -i "s|__USER__|$USER|g" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit config:    nano $APP_DIR/.env"
echo "  2. Start bot:      sudo systemctl start $SERVICE_NAME"
echo "  3. Check logs:     sudo journalctl -u $SERVICE_NAME -f"
echo "  4. Stop bot:       sudo systemctl stop $SERVICE_NAME"
echo "  5. Restart bot:    sudo systemctl restart $SERVICE_NAME"
