# Cloud SaaS Architecture — VNAC

## Mô hình

```
CLOUD CỦA BẠN (Fly.io / VPS)              SERVER GAME (Plugin VNAC)
┌──────────────────────────────┐          ┌──────────────────────────┐
│  FastAPI Server              │          │  Plugin VNAC.jar         │
│                              │          │                          │
│  ┌─ model/ ───────────────┐ │          │  Features: yawJerk, CPS  │
│  │  aim.gbdt  (200KB)     │ │ ←━━━━━━ │  → POST /predict/aim     │
│  │  click.model (200B)    │ │   API   │                          │
│  │  session.json          │ │  Key    │  Risk score: 0.73        │
│  └────────────────────────┘ │ ━━━━━━→ │  ← FusionEngine evaluate │
│                              │          │                          │
│  API Keys:                  │          │  KHÓA có model trong     │
│  ├── server-A: sk-xxx1     │          │  plugin → không ai reverse│
│  ├── server-B: sk-xxx2     │          │  engineer được           │
│  └── server-C: sk-xxx3     │          └──────────────────────────┘
└──────────────────────────────┘
```

## Lợi ích

| Tiêu chí | Local | Cloud SaaS |
|---|---|---|
| Model bị reverse | ✅ Dễ (JAR decompile) | ❌ **Không thể** (trên cloud) |
| Training data | Từng server riêng | **Gộp tất cả servers** → model mạnh hơn |
| Update model | Restart plugin | **Deploy không downtime** |
| Bán product | Bán file JAR | **Bán subscription** → recurring revenue |
| Kiểm soát | Người mua tự do | **Bạn kiểm soát hoàn toàn** |

## API Design

```yaml
# plugins/VNAC/config.yml
VNAC:
  cloud:
    enabled: true
    url: "https://api.vnac.dev"
    api-key: "sk-xxxx-xxxx"    # Key riêng cho từng server
```

### Endpoints

| Endpoint | Method | Mô tả | Tần suất |
|---|---|---|---|
| `/v1/predict/aim` | POST | 6 features → risk score | Mỗi tick combat |
| `/v1/predict/click` | POST | 5 features → risk score | Khi click |
| `/v1/predict/session` | POST | 8 features → risk score | 5s/lần |
| `/v1/train/click` | POST | Online training từ staff label | Khi staff flag |
| `/v1/auth/verify` | POST | Verify API key còn hạn không | Mỗi 1h |

### Response format

```json
{
  "risk": 0.73,
  "confidence": 0.85,
  "model": "aim-gbdt-v2",
  "timestamp": 1749000000
}
```

## Revenue Model

| Gói | Servers | Requests | Giá |
|---|---|---|---|
| Free | 1 | 10k/ngày | $0 |
| Basic | 3 | 50k/ngày | $5/tháng |
| Pro | 10 | 200k/ngày | $15/tháng |
| Enterprise | Unlimited | Unlimited | $50/tháng |

## Rate Limiting

```python
# Mỗi API key:
#   60 requests/min  → free
#   600 requests/min → basic 
#   3000 requests/min → pro
#   unlimited → enterprise
```

## Security

1. **API Key** - mỗi server 1 key riêng, có thể revoke
2. **Rate limit** - chống abuse
3. **Input validation** - chỉ nhận feature vector, không exec code
4. **HTTPS only** - Let's Encrypt
5. **No model in plugin** - decompile JAR cũng không xem được model
