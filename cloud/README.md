# MLSHybridAC Cloud ML Inference Server

FastAPI + LightGBM inference server cho Minecraft anticheat ML system.
1GB RAM VPS optimized.

## Quick Start

```bash
# Setup VPS
sudo bash setup-vps.sh ml.yourdomain.com

# Deploy files
rsync -avz cloud/ root@vps:/opt/ac-ml/cloud/

# Start service
sudo systemctl start ac-ml
sudo journalctl -u ac-ml -f
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/predict/aim` | Aim assist risk (6 features) |
| POST | `/v1/predict/click` | AutoClicker risk (5 features) |
| POST | `/v1/predict/session` | Session profile risk (8 features) |
| POST | `/v1/predict/all` | Composite: all 3 models + fusion |
| POST | `/v1/training/sample` | Submit labeled training sample |
| POST | `/v1/train/trigger` | Trigger model retraining |
| POST | `/v1/auth/verify` | Verify API key |
| POST | `/v1/admin/keys` | Create API key (admin) |
| GET | `/v1/health` | Health check |
| GET | `/v1/metrics` | Prometheus metrics |

## Architecture

```
Server: uvicorn (1 worker, 16 concurrent)
Model: LightGBM (lazy load, TTL unload 5min)
DB: SQLite (WAL mode)
Cache: In-process (optional)
Security: API key + rate limiting
```

## Deployment

See `setup-vps.sh` for full deployment.

## Directory Structure

```
cloud/
├── server.py           # FastAPI app
├── config.py           # Configuration
├── model.py            # ModelRegistry + LightGBM inference
├── auth.py             # API key auth + rate limiting
├── database.py         # SQLite
├── schemas.py          # Pydantic models
├── requirements.txt    # Python deps
├── Dockerfile          # Docker build
├── docker-compose.yml  # Docker deploy
├── nginx.conf          # Nginx reverse proxy
├── systemd.service     # systemd unit
├── setup-vps.sh        # VPS setup script
├── README.md
└── training/
    ├── train.py        # LightGBM training
    ├── labeler.py      # Label pipeline
    └── analyze_features.py  # Feature importance
```
