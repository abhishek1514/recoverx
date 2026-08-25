# RecoverX — AI Revenue Recovery Agent

RecoverX is an autonomous, AI-assisted revenue recovery agent designed to detect and resolve settlement friction for international and high-value payments. It operates alongside Razorpay to identify revenue at risk, estimate recovery probability, recommend next-best actions, collect missing documents, perform deterministic reconciliation, and assist operations teams through structured merchant reviews.

---

## 1. System Architecture

```text
                                  +---------------------------------------+
                                  |       Razorpay Test Gateway           |
                                  |   (Checkout Modal & Webhooks)         |
                                  +-------------------+-------------------+
                                                      |
                                                      | Webhook POST /api/webhooks/razorpay
                                                      v
+-----------------------------+   HTTP / API   +-----------------------------------+
|      Vercel Frontend        | -------------> |     Render Web API (FastAPI)      |
|  (React + Vite Merchant UI) | <------------- |  - Auth & Security Middlewares    |
+-----------------------------+                |  - Timing-Safe HMAC & Replay Guard|
                                               |  - Deterministic Intelligence     |
                                               +-----------------+-----------------+
                                                                 |
                                       +-------------------------+-------------------------+
                                       |                                                   |
                                       v                                                   v
                        +------------------------------+                    +------------------------------+
                        |   Render Background Worker   |                    |      Managed PostgreSQL      |
                        |   - Durable Queue Consumer   | <----------------> |    - Tenant Isolation        |
                        |   - Out-of-Order Resilient   |                    |    - Additive Migrations     |
                        |   - Dead-Letter Queue (DLQ)  |                    |    - Connection Pooling      |
                        +------------------------------+                    +------------------------------+
                                       |
                                       v
                        +------------------------------+
                        |  OpenAI API (Non-Auth / PII) |
                        |  - Guarded Executive Summaries|
                        +------------------------------+
```

---

## 2. Security & Zero Secret Exposure Policy

> [!IMPORTANT]
> **Zero Secret Leakage Guarantee**:
> - API keys, secrets, private keys, and passwords must **NEVER** be committed into Git, written into Dockerfiles, or printed in logs.
> - Secrets are exclusively injected at runtime through hosting environment settings (Render Dashboard & Vercel Dashboard).
> - Default configuration is strictly **Razorpay Test Mode** (`rzp_test_...`). Live payments and credentials are never automated.

### Required Environment Variable Names

| Variable Name | Required / Optional | Description | Configured Where |
| :--- | :--- | :--- | :--- |
| `DATABASE_URL` | **Required** | PostgreSQL connection string (`postgresql://...`) | Render Dashboard |
| `RAZORPAY_KEY_ID` | **Required** | Razorpay Test Key ID (`rzp_test_...`) | Render Dashboard |
| `RAZORPAY_KEY_SECRET` | **Required** | Razorpay Test Key Secret | Render Dashboard |
| `RAZORPAY_WEBHOOK_SECRET`| **Required** | Razorpay Webhook HMAC secret | Render Dashboard |
| `JWT_SECRET` | **Required** | 256-bit cryptographically secure string for JWT signing | Render Dashboard |
| `CORS_ORIGINS` | **Required** | Allowed frontend origin URL (e.g. `https://your-app.vercel.app`) | Render Dashboard |
| `WEBHOOK_TOLERANCE_SECONDS`| Optional | Replay attack tolerance window in seconds (default: `300`) | Render Dashboard |
| `OPENAI_API_KEY` | Optional | OpenAI API key for non-authoritative summaries | Render Dashboard |
| `OPENAI_MODEL` | Optional | OpenAI Model name (e.g. `gpt-4o-mini`) | Render Dashboard |
| `VITE_API_BASE_URL` | **Required** (Frontend) | Public Render backend URL (e.g. `https://recoverx-api.onrender.com`)| Vercel Dashboard |

---

## 3. Automated Deployment Pipeline

RecoverX includes cross-platform automated deployment and preflight verification scripts.

### Windows (PowerShell)
```powershell
# Run full automated validation, tests, frontend build, and smoke check
.\scripts\deploy.ps1 -TargetUrl "https://your-backend.onrender.com"
```

### Linux / macOS / CI (Bash)
```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh "https://your-backend.onrender.com"
```

The automated pipeline performs:
1. Preflight tooling verification (`git`, `python`, `npm`).
2. Repository secret leak scan.
3. Backend unit, integration, and security test suite (78 tests).
4. Frontend production asset compilation (`npm run build`).
5. Deployment manifest integrity checks (`render.yaml`, `vercel.json`, `Dockerfile`, `docker-compose.yml`).
6. Automated post-deployment smoke test (`scripts/smoke_test.py`).

---

## 4. Cloud Platform Deployment Steps

### Step A: Deploy Backend & Worker on Render

1. Log in to [Render Dashboard](https://dashboard.render.com/).
2. Click **New +** $\rightarrow$ **Blueprint**.
3. Connect your RecoverX repository.
4. Render will automatically detect [`render.yaml`](file:///d:/real%20think/recoveryX/recoverx/render.yaml) and configure:
   - **`recoverx-api`**: FastAPI Web Service (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`)
   - **`recoverx-worker`**: Background Worker (`python -m app.workers.worker`)
   - **`recoverx-postgres`**: Managed PostgreSQL Database
5. Under Environment Variables for `recoverx-api` and `recoverx-worker`, enter your secure credentials:
   - `RAZORPAY_KEY_ID`: `rzp_test_...`
   - `RAZORPAY_KEY_SECRET`: `...`
   - `RAZORPAY_WEBHOOK_SECRET`: `...`
   - `CORS_ORIGINS`: `https://<YOUR_VERCEL_DOMAIN>.vercel.app`
   - `OPENAI_API_KEY`: *(Optional)*
6. Click **Apply**. Render will provision PostgreSQL, build the services, and launch the API and Worker.

### Step B: Deploy Frontend on Vercel

1. Log in to [Vercel Dashboard](https://vercel.com/).
2. Click **Add New Project** and select the RecoverX repository.
3. In Project Settings:
   - **Root Directory**: `frontend`
   - **Framework Preset**: `Vite`
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`
4. Under **Environment Variables**, add:
   - `VITE_API_BASE_URL`: `https://<YOUR_RENDER_BACKEND_URL>.onrender.com`
5. Click **Deploy**. Vercel will build and publish the production frontend.

### Step C: Configure Razorpay Test Webhook

1. Open your [Razorpay Dashboard](https://dashboard.razorpay.com/) in **Test Mode**.
2. Navigate to **Settings → Webhooks → Add Webhook**.
3. Enter:
   - **Webhook URL**: `https://<YOUR_RENDER_BACKEND_URL>.onrender.com/api/webhooks/razorpay`
   - **Secret**: (must match `RAZORPAY_WEBHOOK_SECRET` configured in Render)
   - **Active Events**: `payment.captured`, `payment.failed`, `order.paid`
4. Save the webhook.

---

## 5. Post-Deployment Verification & Smoke Testing

Run the automated smoke test suite against your deployed environment:

```bash
python scripts/smoke_test.py --url https://<YOUR_RENDER_BACKEND_URL>.onrender.com
```

The smoke test verifies:
- `GET /health/live` (Process liveness)
- `GET /health/ready` (Database pool connectivity & queue status)
- Production security headers (`nosniff`, `DENY`, `X-Request-ID`)
- Unauthorized request rejection (HTTP 401 on protected endpoints)
- Merchant login & tenant-scoped dashboard metrics query

---

## 6. Concurrency & Load Testing (k6)

RecoverX includes a standardized k6 concurrency benchmark in [`load_tests/k6_load_test.js`](file:///d:/real%20think/recoveryX/recoverx/load_tests/k6_load_test.js).

### Run Load Benchmarks
```bash
# Benchmark local staging environment
k6 run load_tests/k6_load_test.js -e BASE_URL=http://localhost:8000

# Benchmark deployed staging backend
k6 run load_tests/k6_load_test.js -e BASE_URL=https://<YOUR_RENDER_BACKEND_URL>.onrender.com
```

### Load Testing Scenarios & SLA Metrics
The test benchmarks **10**, **50**, and **100 concurrent Virtual Users (VUs)** and measures:
- **Webhook ACK Latency**: $p(95) < 200\text{ms}$ (asynchronous ingestion).
- **Liveness & Readiness**: $p(95) < 100\text{ms}$.
- **Throughput**: Requests Per Second (RPS) sustained under peak concurrency.
- **Error Rate**: Strict threshold $< 1.0\%$.

---

## 7. Resilience & Failure Verification

| Failure Scenario | Built-in Protection Mechanism | Verification Command / Step |
| :--- | :--- | :--- |
| **Worker Process Crash** | Render automatically restarts process; database state is preserved without data loss | Kill worker process $\rightarrow$ restart worker $\rightarrow$ picks up pending events |
| **Transient Webhook Failure** | Durable queue exponential backoff retry (up to 3 retries) | Ingest event with simulated transient DB lock |
| **Poison / Fatal Webhook Event**| Automatic Dead-Letter Queue (`DLQ`) transition with audit log | Inspect `webhook_events.status == 'dead_letter'` |
| **Duplicate Webhook Delivery** | Database unique constraint on `event_id` returns fast HTTP 200 `duplicate: true` | Send same webhook payload twice |
| **Replay Attack** | Timestamps older than `WEBHOOK_TOLERANCE_SECONDS` rejected with HTTP 400 | Run `test_06_webhook_replay_protection_rejects_stale_event` |
| **Invalid HMAC Signature** | Server-side timing-safe comparison (`hmac.compare_digest`) returns HTTP 401 | Run `test_invalid_signature` |
| **OpenAI Outage / Timeout** | Graceful fallback retaining deterministic recovery decisions and next-best actions | Run `test_ai_graceful_fallback_preserves_deterministic_recovery` |
| **Cross-Tenant Breach Attempt** | Strict `verify_merchant_ownership` asserts resource ownership; returns HTTP 403 | Run `test_04_cross_merchant_case_access_forbidden` |

---

## 8. Local Development & Staging Setup

### Local SQLite Development
```powershell
# 1. Backend setup
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload

# 2. Frontend setup (in a new terminal)
cd frontend
npm install
npm run dev
```

### Local Staging via Docker Compose (PostgreSQL + API + Worker + Frontend)
```bash
docker-compose up --build
```

---

## 9. Production Readiness Checklist

- [x] Zero hardcoded secrets in source files, Dockerfiles, or Git history.
- [x] All 78 backend unit, integration, and security tests passing.
- [x] Frontend production bundle compiles cleanly with Vite (`npm run build`).
- [x] Multi-tenant isolation verified with cross-merchant rejection tests.
- [x] PostgreSQL connection pooling and non-destructive schema migrations configured.
- [x] Replay attack defense and timing-safe webhook HMAC verification active.
- [x] Dedicated background worker process entrypoint implemented.
- [x] Private document storage with binary magic-byte inspection and signed URLs.
- [x] PII scrubbing and untrusted content encapsulation guardrails active.
- [x] Automated deployment scripts (`deploy.ps1`, `deploy.sh`), smoke tests, and k6 load tests created.
