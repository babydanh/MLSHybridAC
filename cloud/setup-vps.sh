#!/usr/bin/env bash
#============================================================================
# MLSHybridAC Cloud VPS Setup Script
# Target: Ubuntu 22.04 LTS, 1GB RAM
# Usage: sudo bash setup-vps.sh your-domain.com
#============================================================================
set -euo pipefail

DOMAIN="${1:-}"
if [ -z "$DOMAIN" ]; then
    echo "Usage: $0 your-domain.com"
    echo "Example: sudo bash setup-vps.sh ml.ac.yourdomain.com"
    exit 1
fi

echo "=== MLSHybridAC Cloud VPS Setup ==="
echo "Domain: $DOMAIN"
echo "Target: Ubuntu 22.04, 1GB RAM"
echo ""

# ── System updates ────────────────────────────────────────────────────────
apt update && apt upgrade -y
apt install -y nginx certbot python3 python3-venv python3-pip git curl ufw fail2ban

# ── Firewall ──────────────────────────────────────────────────────────────
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw --force enable

# ── Create user ───────────────────────────────────────────────────────────
if ! id acml &>/dev/null; then
    useradd -m -s /bin/bash acml
fi
mkdir -p /opt/ac-ml/data/models /opt/ac-ml/data/training
chown -R acml:acml /opt/ac-ml

# ── Python venv ───────────────────────────────────────────────────────────
python3 -m venv /opt/ac-ml/venv
source /opt/ac-ml/venv/bin/activate
pip install --upgrade pip
pip install -r /opt/ac-ml/cloud/requirements.txt
deactivate

# ── Let's Encrypt SSL ─────────────────────────────────────────────────────
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email admin@"$DOMAIN" || {
    echo "WARNING: Let's Encrypt failed. You may need to run certbot manually:"
    echo "  sudo certbot --nginx -d $DOMAIN"
}

# Auto-renewal
systemctl enable certbot.timer

# ── Setup app ─────────────────────────────────────────────────────────────
if [ -d "/opt/ac-ml/cloud" ]; then
    cd /opt/ac-ml
    # Link model directory
    mkdir -p /opt/ac-ml/data/models
    # Copy service file
    cp cloud/systemd.service /etc/systemd/system/ac-ml.service
    systemctl daemon-reload
    systemctl enable ac-ml

    echo "=== Setup complete! ==="
    echo ""
    echo "Next steps:"
    echo "  1. Edit /etc/systemd/system/ac-ml.service and set ML_ADMIN_KEY"
    echo "  2. Place model files in /opt/ac-ml/data/models/"
    echo "  3. Start the server: sudo systemctl start ac-ml"
    echo "  4. Check logs: sudo journalctl -u ac-ml -f"
    echo ""
    echo "Admin key setup:"
    echo "  sudo systemctl edit ac-ml  # add Environment=ML_ADMIN_KEY=sk-..."
    echo "  sudo systemctl restart ac-ml"
    echo ""
    echo "Test:"
    echo "  curl -k https://$DOMAIN/v1/health"
else
    echo "WARNING: /opt/ac-ml/cloud not found."
    echo "Please copy the cloud/ directory to /opt/ac-ml/ before starting."
fi

# ── Fail2ban ──────────────────────────────────────────────────────────────
cat > /etc/fail2ban/jail.local << 'EOF'
[acml-auth]
enabled = true
port = 443
filter = acml-auth
logpath = /var/log/nginx/acml-access.log
maxretry = 5
bantime = 900
findtime = 600
EOF

cat > /etc/fail2ban/filter.d/acml-auth.conf << 'EOF'
[Definition]
failregex = ^.* 401 .* "POST /v1/.*" .*$
ignoreregex =
EOF

systemctl restart fail2ban

echo "=== Done! ==="
