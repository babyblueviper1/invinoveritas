# DEPLOY.md — invinoveritas v1.1.1 Deployment Guide

**Workflow: VPS first → test → GitHub → PyPI**

---

## Table of Contents

1. [VPS Deployment](#1-vps-deployment)
2. [Environment Variables](#2-environment-variables)
3. [Data Directory Setup](#3-data-directory-setup)
4. [Systemd Service Management](#4-systemd-service-management)
5. [Zero-Downtime Restart](#5-zero-downtime-restart)
6. [Logging & Monitoring](#6-logging--monitoring)
7. [Push to GitHub](#7-push-to-github)
8. [Release SDK to PyPI](#8-release-sdk-to-pypi)
9. [Post-Release Checklist](#9-post-release-checklist)
10. [Rollback](#10-rollback)

---

## 1. VPS Deployment

### Pull the latest code

```bash
cd /root/invinoveritas
git pull origin main      # or paste the updated files from this session
```

If you're applying this upgrade manually (no git on VPS):
```bash
# The files were already updated in this session. Just restart the services.
```

### Install/update dependencies

```bash
cd /root/invinoveritas
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt  # or manually:
pip install fastapi uvicorn httpx requests python-dotenv pydantic
```

---

## 2. Environment Variables

Edit your `.env` file (or systemd `EnvironmentFile`):

```bash
nano /root/invinoveritas/.env
```

Required:
```env
# AI
OPENAI_API_KEY=sk-...

# Lightning bridge (local bridge.py)
NODE_URL=http://127.0.0.1:8081

# Marketplace
PLATFORM_CUT_PERCENT=5.0
PLATFORM_LN_ADDRESS=your@getalby.com    # platform Lightning Address for 5% cut
MARKETPLACE_MIN_PRICE_SATS=1000
```

Optional but recommended:
```env
# NWC wallet (Alby, Zeus, Mutiny) — for autonomous agent payments
NWC_CONNECTION_URI=nostr+walletconnect://...

# Nostr announcements
NOSTR_NSEC=your-hex-nsec

# Data directory (VPS path — already set as default)
VPS_DATA_DIR=/root/invinoveritas/data

# Pricing overrides
REASONING_PRICE_SATS=500
DECISION_PRICE_SATS=1000
ORCHESTRATE_PRICE_SATS=2000
```

---

## 3. Data Directory Setup

The v1.1.1 upgrade moves storage from `/opt/render/...` to `/root/invinoveritas/data/`:

```bash
mkdir -p /root/invinoveritas/data
chmod 700 /root/invinoveritas/data
```

The app will auto-create `marketplace.db`, `used_payments.db`, and  
`invinoveritas_announcements.json` on first start.

---

## 4. Systemd Service Management

### Main API (app.py)

Check/view service:
```bash
systemctl status invinoveritas
journalctl -u invinoveritas -f --no-pager
```

Restart after update:
```bash
systemctl restart invinoveritas
systemctl status invinoveritas   # confirm it's running
```

If you don't have a systemd unit yet, create one:
```bash
cat > /etc/systemd/system/invinoveritas.service << 'EOF'
[Unit]
Description=invinoveritas API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/invinoveritas
EnvironmentFile=/root/invinoveritas/.env
ExecStart=/root/invinoveritas/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable invinoveritas
systemctl start invinoveritas
```

### Lightning Bridge (bridge.py)

```bash
systemctl status invinoveritas-bridge
systemctl restart invinoveritas-bridge
```

If creating the bridge unit:
```bash
cat > /etc/systemd/system/invinoveritas-bridge.service << 'EOF'
[Unit]
Description=invinoveritas Lightning Bridge
After=network.target lnd.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/invinoveritas
EnvironmentFile=/root/invinoveritas/.env
ExecStart=/root/invinoveritas/venv/bin/uvicorn bridge:app --host 127.0.0.1 --port 8081
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable invinoveritas-bridge
systemctl start invinoveritas-bridge
```

---

## 5. Zero-Downtime Restart

For near-zero-downtime, use a rolling reload (2+ workers):

```bash
# Send SIGHUP to uvicorn to gracefully reload workers
PID=$(systemctl show -p MainPID invinoveritas | cut -d= -f2)
kill -HUP $PID
# Workers reload one at a time without dropping connections
```

Or use the systemd approach (tiny gap, ~1s):
```bash
systemctl reload-or-restart invinoveritas
```

---

## 6. Logging & Monitoring

### Live logs
```bash
# API
journalctl -u invinoveritas -f

# Bridge
journalctl -u invinoveritas-bridge -f

# Both
journalctl -u invinoveritas -u invinoveritas-bridge -f
```

### Health check
```bash
curl https://api.babyblueviper.com/health
# Expected: {"status": "ok", "version": "1.1.1", ...}
```

### New v1.1.1 endpoints smoke test
```bash
# Marketplace
curl https://api.babyblueviper.com/offers/list

# Analytics (requires Bearer token)
curl -H "Authorization: Bearer YOUR_KEY" https://api.babyblueviper.com/analytics/roi

# Orchestrate
curl -X POST https://api.babyblueviper.com/orchestrate \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tasks": [{"id": "t1", "type": "reason", "input": {"question": "test"}, "depends_on": []}]}'
```

### Automated health check script
```bash
#!/bin/bash
# /root/health-check.sh
STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://api.babyblueviper.com/health)
if [ "$STATUS" != "200" ]; then
    echo "ALERT: API returned $STATUS — restarting"
    systemctl restart invinoveritas
fi
```

Add to cron:
```bash
crontab -e
# Add: */5 * * * * /root/health-check.sh
```

---

## 7. Push to GitHub

After testing on VPS:

```bash
cd /root/invinoveritas

# Stage only the files we changed
git add config.py app.py bridge.py node_bridge.py mcp_server.py DEPLOY.md
git add sdk/pyproject.toml sdk/README.md
git add sdk/invinoveritas/__init__.py sdk/invinoveritas/marketplace.py sdk/invinoveritas/smart.py
git add examples/marketplace/agent_revenue_demo.py
git add examples/trading/trading_bot_net_profit.py

git commit -m "feat: v1.1.1 — marketplace, orchestration, analytics, NWC defaults

- Agent Marketplace: /offers/create|list|buy|my (5% platform, 95% seller instant)
- Multi-agent orchestration: /orchestrate with dependency graph + risk scoring
- Analytics: /analytics/spend, /analytics/roi, /analytics/memory
- optimize_call() SDK helper for cost routing
- policy={} governance hooks on all calls
- NWC as recommended default wallet
- VPS-first: PERSISTENT_DIR migrated from Render to /root/invinoveritas/data
- Trading bot net-profit demo
- Updated all URLs to api.babyblueviper.com"

# Push (you'll be prompted for your GitHub token)
git push origin main
```

If you need to set up the remote first:
```bash
git remote set-url origin https://YOUR_GITHUB_TOKEN@github.com/babyblueviper1/invinoveritas.git
git push origin main
```

---

## 8. Release SDK to PyPI

```bash
cd /root/invinoveritas/sdk

# Activate venv
source /root/invinoveritas/venv/bin/activate

# Install build tools (once)
pip install --upgrade build twine

# Build the distribution
python -m build
# Creates: dist/invinoveritas-1.1.1-py3-none-any.whl
#          dist/invinoveritas-1.1.1.tar.gz

# Verify the build
ls -la dist/
twine check dist/*

# Upload to PyPI
# Set your PyPI token as an env var (never paste tokens in plain text):
#   export PYPI_TOKEN="pypi-..."
twine upload dist/* --username __token__ --password "$PYPI_TOKEN"
```

Verify it's live:
```bash
pip install --upgrade invinoveritas
python -c "import invinoveritas; print(invinoveritas.__version__)"
# Expected: 1.1.1
```

---

## 9. Post-Release Checklist

- [ ] `curl https://api.babyblueviper.com/health` returns `"version": "1.1.1"`
- [ ] `curl https://api.babyblueviper.com/offers/list` returns `{"offers": [], ...}`
- [ ] `pip install --upgrade invinoveritas && python -c "import invinoveritas; print(invinoveritas.__version__)"` prints `1.1.1`
- [ ] GitHub shows the v1.1.1 commit
- [ ] Create GitHub release tag: `git tag v1.1.1 && git push origin v1.1.1`
- [ ] Post release notes to socials (see below)
- [ ] Update MCP registry if needed: https://registry.modelcontextprotocol.io

---

## 10. Rollback

If something goes wrong, roll back within 60 seconds:

```bash
# Option A: git revert
cd /root/invinoveritas
git stash                    # stash changes
systemctl restart invinoveritas

# Option B: restore from backup (if you made one)
cp app.py.backup app.py
systemctl restart invinoveritas
```

Make a backup before every deploy:
```bash
cp /root/invinoveritas/app.py /root/invinoveritas/app.py.v1.0.backup
cp /root/invinoveritas/bridge.py /root/invinoveritas/bridge.py.v1.0.backup
```

---

## Quick Reference: All Commands

```bash
# Deploy
systemctl restart invinoveritas invinoveritas-bridge

# Check
curl https://api.babyblueviper.com/health
journalctl -u invinoveritas -f

# Build SDK
cd /root/invinoveritas/sdk && python -m build

# Release to PyPI
twine upload dist/* --username __token__ --password <pypi-token>

# Push to GitHub
git add -A && git commit -m "v1.1.1" && git push origin main
```
