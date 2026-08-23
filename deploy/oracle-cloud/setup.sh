#!/bin/bash
# ==============================================================================
# CIE-OS Oracle Cloud VM Bootstrap Script
# ==============================================================================
# Run this on a fresh Ubuntu 22.04/24.04 ARM instance.
#
# Usage:
#   chmod +x setup.sh
#   sudo ./setup.sh
# ==============================================================================

set -euo pipefail

INSTALL_DIR="/opt/cie-os"
REPO_URL="${CIE_OS_REPO_URL:-}"

echo "=== CIE-OS Oracle Cloud Setup ==="

# --- System packages ---
echo "[1/6] Installing system packages..."
apt-get update
apt-get install -y --no-install-recommends \
    docker.io \
    docker-compose-v2 \
    git \
    curl \
    ufw

# --- Docker ---
echo "[2/6] Configuring Docker..."
systemctl enable docker
systemctl start docker
usermod -aG docker ubuntu 2>/dev/null || usermod -aG docker "$SUDO_USER" 2>/dev/null || true

# --- Firewall ---
echo "[3/6] Configuring firewall..."
ufw --force enable
ufw allow 22/tcp
ufw allow 8801/tcp
ufw reload

# --- Project directory ---
echo "[4/6] Setting up project directory..."
mkdir -p "$INSTALL_DIR"

if [ -n "$REPO_URL" ]; then
    git clone "$REPO_URL" "$INSTALL_DIR"
else
    echo "  NOTE: Set CIE_OS_REPO_URL env var or copy project files to $INSTALL_DIR manually."
    echo "  Example: scp -r ./CIE-OS/* ubuntu@<vm-ip>:$INSTALL_DIR/"
fi

# --- Environment file ---
echo "[5/6] Setting up environment..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
    if [ -f "$INSTALL_DIR/.env.production.example" ]; then
        cp "$INSTALL_DIR/.env.production.example" "$INSTALL_DIR/.env"
        chmod 600 "$INSTALL_DIR/.env"
        echo "  Created .env from template. Edit it: nano $INSTALL_DIR/.env"
    fi
fi

# --- Systemd units ---
echo "[6/6] Installing systemd services..."
cp "$INSTALL_DIR/deploy/oracle-cloud/cie-os-api.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/oracle-cloud/cie-os-ingest.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/oracle-cloud/cie-os-ingest.timer" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/oracle-cloud/cie-os-scan.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/oracle-cloud/cie-os-scan.timer" /etc/systemd/system/

systemctl daemon-reload
systemctl enable cie-os-api.service
systemctl enable cie-os-ingest.timer
systemctl enable cie-os-scan.timer

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Copy project files to $INSTALL_DIR (if not cloned)"
echo "  2. Edit API keys:  sudo nano $INSTALL_DIR/.env"
echo "  3. Build images:   cd $INSTALL_DIR && docker compose build"
echo "  4. Start API:      sudo systemctl start cie-os-api"
echo "  5. Start timers:   sudo systemctl start cie-os-ingest.timer cie-os-scan.timer"
echo "  6. Verify:         curl http://localhost:8801/health"
echo ""
echo "Logs:"
echo "  API:     docker compose -f $INSTALL_DIR/docker-compose.yml logs -f a01-api"
echo "  Ingest:  journalctl -u cie-os-ingest.service -f"
echo "  Scan:    journalctl -u cie-os-scan.service -f"
