RecoverX — AI-Assisted Revenue Recovery Agent

RecoverX is a revenue recovery operations platform designed to help merchants identify, prioritize, analyze, and resolve revenue exceptions across payments, settlements, reconciliation, and disputes.

1. Core Business Workflow

Revenue Event
     ↓
Validation
     ↓
Idempotency
     ↓
Durable Persistence
     ↓
Background Processing
     ↓
Exception Detection
     ↓
Recovery Case
     ↓
Risk Assessment
     ↓
Next Best Action
     ↓
Merchant Action
     ↓
Resolution
     ↓
Audit Trail

Current status: RecoverX is actively developed and has a verified local Docker-based environment. Production deployment and some end-to-end integrations are still pending verification.

2. What RecoverX Does

RecoverX brings revenue-recovery operations into one merchant-facing workspace.

It is designed to:

Detect revenue exceptions.

Identify revenue at risk.

Prioritize cases by urgency.

Assess recovery risk/probability.

Recommend next-best actions.

Manage recovery cases.

Support disputes and chargebacks.

Track settlements and reconciliation issues.

Store recovery evidence/documents.

Maintain an audit trail.

Integrate with Razorpay Test Mode.

The goal is to turn a revenue exception into a structured recovery action.

3. System Architecture

Local / Staging

                    ┌─────────────────────────┐
                    │   Razorpay Test Mode    │
                    │ Checkout + Webhooks      │
                    └────────────┬────────────┘
                                 │
                                 ▼
┌─────────────────────┐   ┌──────────────────────────┐
│ React + Vite        │──▶│ RecoverX FastAPI API     │
│ Merchant Frontend   │◀──│ Authentication           │
└─────────────────────┘   │ Validation               │
                          │ Business APIs             │
                          └───────────┬──────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
             ┌────────────┐   ┌────────────┐   ┌────────────┐
             │ PostgreSQL │   │   Redis    │   │   MinIO    │
             │ Database   │   │ Rate Limit │   │ Documents  │
             └─────┬──────┘   └────────────┘   └────────────┘
                   │
                   ▼
             ┌────────────────────┐
             │ RecoverX Worker    │
             │ Background Jobs    │
             └─────────┬──────────┘
                       ▼
                 Recovery Processing

Production Target

The repository also contains deployment configuration/documentation for a cloud setup using Vercel for the frontend and Render for the FastAPI API, worker, and managed PostgreSQL.

Production documentation describes the target architecture; it should only be marked deployed after independent verification.

4. Frontend

Technology:

React

Vite

Main product areas:

/login
/signup
/dashboard
/exceptions
/disputes
/settlements
/payments
/needs-attention
/transactions/new
/pay
/settings

Dashboard

Provides a unified view of revenue recovery operations, including:

Revenue at Risk

Cases Needing Action

Recovered Revenue

Recovery Likelihood

Revenue Exceptions

Exceptions can be prioritized by:

Critical

High

Medium

Low

Categories include:

Disputes

Settlements

Reconciliation

Payment State

Recovery Cases

Cases can contain:

Amount at Risk

Priority

Risk assessment

Recovery probability

Status/stage

Next Best Action

Evidence

Resolution history

5. Authentication

Current authentication:

Email + Password
       ↓
Authentication API
       ↓
JWT Access Token
       ↓
Authenticated Frontend Session

Frontend auth storage:

recoverx_access_token
recoverx_user

Protected application routes require authentication.

Merchant Signup

Merchant signup has been implemented:

/signup
   ↓
Business / Merchant Name
Full Name
Email
Password
Confirm Password
   ↓
Create Merchant
   ↓
Create User
   ↓
Link User → Merchant
   ↓
Hash Password
   ↓
Issue JWT
   ↓
Dashboard

The backend controls merchant_id, role, and user ID.

Current Authentication Status

Email/password login: implemented.

Merchant signup: implemented.

JWT authentication: implemented.

Merchant-specific authorization: implemented.

Google OAuth: not yet implemented.

6. Multi-Tenant Merchant Isolation

Merchant is the tenant boundary.

Merchant
 ├── Users
 ├── Customers
 ├── Transactions
 ├── Recovery Cases
 ├── Disputes
 ├── Settlements
 ├── Documents
 └── Audit Logs

Users are linked to merchants through:

users.merchant_id → merchants.id

Merchant-scoped backend operations must use the authenticated user's merchant context.

The frontend must never be trusted to choose which merchant's data can be accessed.

7. Backend

Technology:

Python

FastAPI

SQLAlchemy

Pydantic

Major areas:

Authentication
Dashboard
Recovery Cases
Payments
Disputes
Settlements
Reconciliation
Webhooks
Health / Diagnostics

The backend handles authentication, authorization, merchant isolation, payment/order APIs, webhook validation, idempotent event handling, recovery-case processing, risk/recovery analysis, document authorization/storage, and audit logging.

8. Durable Webhook Processing

External Webhook
      ↓
FastAPI
      ↓
Signature Verification
      ↓
Idempotency Check
      ↓
Persist Event
      ↓
Durable Queue
      ↓
Fast Response
      ↓
Background Worker
      ↓
Business Processing

Financial webhook processing should not depend on an in-memory queue.

Duplicate Webhooks

Repeated delivery of the same event should produce one logical processing result rather than duplicate financial records.

Security

Webhook processing includes:

HMAC signature validation.

Replay protection.

Idempotency.

Merchant/resource authorization.

9. Background Worker

The worker is separate from the API.

Responsibilities:

Consume durable events.

Process pending webhook events.

Normalize external events.

Update transactions.

Create/update recovery cases.

Run background analysis.

Update processing state.

Write audit information.

API
 ↓
Durable Event
 ↓
Worker
 ↓
Recovery Processing

The worker is not the HTTP API server.

10. Risk & Next-Best-Action Layer

RecoverX evaluates recovery context and produces:

Risk Score
Priority
Amount at Risk
Recovery Probability
Next Best Action

Example action concepts include:

SUBMIT_REPRESENTMENT
REQUEST_INVOICE
MERCHANT_REVIEW

AI-assisted analysis must not bypass authentication, authorization, merchant isolation, financial validation, idempotency, or deterministic business rules.

11. PostgreSQL Data Model

Core entities include:

merchants
users
customers
transactions
recovery_cases
documents
risk_assessments
actions
validation_results
webhook_events
audit_logs

Revenue operations also include:

disputes
settlements
reconciliation

Important relationship:

Merchant
   ↓
User
   ↓
merchant_id

12. Redis

Redis is used for distributed API rate limiting.

Request
   ↓
FastAPI
   ↓
Redis Rate Limiter
   ↓
Allow / Reject

13. Secure Document Storage

Local environment:

MinIO

Production target:

S3-compatible object storage

Flow:

Document Upload
      ↓
Authentication
      ↓
Merchant Authorization
      ↓
File Validation
      ↓
Object Storage
      ↓
Recovery Case

Private documents should not be exposed as public objects.

14. Audit Trail

Important recovery operations are intended to remain traceable.

Examples:

CASE_ANALYZED
EVIDENCE_SUBMITTED
MERCHANT_APPROVED
SETTLEMENT_SYNCED
RECONCILIATION_FLAGGED
DISPUTE_CONTESTED

15. Razorpay Integration

RecoverX integrates with Razorpay Test Mode.

RecoverX
   ↓
Create Razorpay Test Order
   ↓
Razorpay Standard Checkout
   ↓
Test Payment Event
   ↓
Razorpay Webhook
   ↓
RecoverX Webhook Processing

The checkout has successfully opened in the current local environment.

No real-money payment is required for the local demo.

Successful checkout alone does not prove the entire webhook → worker → recovery-case chain; that chain must be verified separately.

16. Security & Secrets

Secrets must never be committed to Git.

Examples:

RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
JWT_SECRET
DATABASE_URL
OPENAI_API_KEY

Local secrets belong in:

.env

Templates belong in:

.env.example

Never put real credentials into .env.example.

Never:

Commit .env.

Log passwords.

Log JWT tokens.

Commit Razorpay secrets.

Put backend secrets in frontend JavaScript.

Trust client-provided merchant IDs.

Expose private documents publicly.

17. Docker Local Environment

Services:

recoverx-api
recoverx-worker
recoverx-postgres
recoverx-redis
recoverx-minio
recoverx-minio-init

Start:

docker compose up -d --build

Check:

docker compose ps

API logs:

docker compose logs --tail=100 backend-api

Worker logs:

docker compose logs --tail=100 backend-worker

Health:

http://localhost:8000/health/live

Frontend:

http://localhost:5173

18. Testing & Verification

Current reported verification

After merchant signup implementation:

Focused signup tests:       4/4 passed
Full backend suite:         172 tests passed
Frontend production build:  passed
Docker Compose config:      passed
Docker services:            healthy during verification
.env:                       not staged or committed

Automated tests do not by themselves prove production readiness.

Production still requires independent verification of:

Cloud deployment.

Production database.

Production Redis.

Production object storage.

Production Razorpay webhook delivery.

HTTPS/CORS.

Monitoring.

Backups.

Rollback.

Full production E2E.

19. Production Deployment

The repository contains configuration/documentation for:

Backend / Worker

Target:

Render

Services:

recoverx-api
recoverx-worker
Managed PostgreSQL

Frontend

Target:

Vercel

Razorpay Test Webhook

Endpoint:

/api/webhooks/razorpay

Production deployment should only be marked complete after the deployed environment has been independently verified.

20. Load & Resilience Testing

The repository contains tooling for scenarios including:

Concurrent users.

Webhook latency.

API liveness/readiness.

Error-rate measurement.

Worker crash recovery.

Duplicate webhook delivery.

Replay protection.

Invalid webhook signatures.

Cross-tenant access attempts.

AI timeout/fallback behavior.

These are engineering verification tools, not user-facing product features.

21. Current Project Status

Implemented / Locally Verified

React + Vite frontend.

FastAPI backend.

PostgreSQL.

Background worker.

JWT authentication.

Merchant isolation.

Merchant signup.

Durable webhook processing.

Idempotent webhook handling.

Redis rate limiting.

MinIO object storage.

Recovery cases.

Risk/recovery analysis components.

Dispute workflows.

Settlement workflows.

Reconciliation workflows.

Audit logging.

Razorpay Test Mode checkout.

172 backend tests reported passing after signup work.

Frontend production build.

Docker Compose configuration.

Local Docker services.

Pending / Not Yet Implemented

Google OAuth login.

Production cloud deployment verification.

Full production Razorpay webhook E2E verification.

Production monitoring and alerting.

Production backup/restore verification.

Browser verification of signup if the previously observed /signup “Not Found” issue still occurs.

22. Development Rules for AI Coding Agents

If an AI coding agent works on RecoverX:

Read this README.

Inspect the actual repository.

Inspect relevant models.

Inspect API routes.

Inspect services.

Inspect the frontend API client.

Inspect authentication dependencies.

Inspect tests.

Check git status.

Check recent commits.

Then:

Discover
   ↓
Understand
   ↓
Plan
   ↓
Minimal Change
   ↓
Test
   ↓
Security Check
   ↓
Docker / E2E Check
   ↓
Git Diff
   ↓
Commit

Do not:

Rewrite working architecture without a reason.

Create duplicate authentication systems.

Create duplicate API clients.

Bypass merchant authorization.

Trust frontend tenant identifiers.

Store plaintext passwords.

Use floats for financial amounts.

Bypass webhook validation.

Bypass idempotency.

Commit .env.

Invent undocumented APIs without inspecting the code.

The actual source code is the final source of truth.

If this README conflicts with the implementation, inspect the repository and report the discrepancy instead of silently assuming the README is correct.

23. Roadmap

Current Local Product
        ↓
Browser Signup Verification
        ↓
Google OAuth
        ↓
Production Deployment
        ↓
Production Razorpay Webhook Verification
        ↓
Monitoring + Backups
        ↓
Production SaaS Hardening

24. Product Demo Flow

For a product demonstration:

Login
  ↓
Dashboard
  ↓
Revenue Exception
  ↓
Recovery Case
  ↓
Risk / Amount at Risk
  ↓
Next Best Action
  ↓
Merchant Review
  ↓
Resolution

Technical architecture can be shown separately:

Frontend
   ↓
FastAPI
   ↓
PostgreSQL / Redis / Object Storage
   ↓
Durable Queue
   ↓
Worker
   ↓
Recovery Processing
