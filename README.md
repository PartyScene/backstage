# PartyScene Backend

**Production-grade microservices platform for real-time social event discovery, ticketing, and live streaming.**

[![Production Status](https://img.shields.io/badge/status-production-green.svg)]()
[![Python](https://img.shields.io/badge/python-3.13-blue.svg)]()
[![Microservices](https://img.shields.io/badge/services-7%20deployed-blue.svg)]()
[![Tests](https://img.shields.io/badge/tests-200+-yellow.svg)]()

Location-based social platform combining event management, live streaming, AI-powered recommendations, and dual-provider payments — built on async Python (Quart) with a Rust-based ASGI server, deployed to GKE.

---

## System Architecture

### Overview

Cloud-native microservices platform built on Quart (async Python) served by Granian (Rust ASGI server with uvloop). All services share a common `MicroService` base class that initializes SurrealDB connection pools (via purreal), Redis, JWT, RabbitMQ, Prometheus metrics, and a KPI aggregator. Deployed to Google Kubernetes Engine (us-central1) via Cloud Build.

### Core Capabilities

- **Geospatial Discovery**: SurrealDB `geo::distance` queries with indexed coordinates, radius-based event search with pagination
- **Graph Social Layer**: SurrealDB relation tables (`friends`, `blocks`, `attends`, `guestlists`) with multi-degree traversal (`fn::exists_in_degree` up to 5 hops) for private event access control
- **AI Recommendations**: SurrealDB native HNSW vector indexes (768-dim ViT embeddings) for visual similarity search across event media, with cosine + KNN distance scoring
- **Async Media Pipeline**: RabbitMQ (via FastStream) for image compression (Pillow, 2048px max, JPEG Q90), video transcoding (FFmpeg, H.264 CRF 21, 1080p, 5M bitrate), thumbnail extraction, and BlurHash generation
- **Dual-Provider Payments**: Stripe (international) + Paystack (Africa) with webhook-driven ticket creation, tier capacity tracking, and host notification
- **Live Streaming**: GetStream.io Video + Chat SDKs with backstage → go-live flow, geofenced attendee role management (1km radius), and per-event chat channels
- **Real-time KPIs**: Prometheus counters across all services + SurrealDB aggregate queries (DAU/WAU/MAU, retention cohorts, churn, ARPU, conversion), served at `GET /auth/kpis` for Grafana Infinity

### Microservices

```
              ┌──────────────────────────────────────────────────┐
              │              GKE Ingress / Load Balancer          │
              └────────────────────┬─────────────────────────────┘
                                   │
         ┌─────────┬───────────┬───┴───┬───────────┬─────────────┐
         │         │           │       │           │             │
    ┌────▼───┐ ┌───▼───┐ ┌────▼──┐ ┌──▼───┐ ┌────▼────┐ ┌─────▼────┐
    │  Auth  │ │ Users │ │Events │ │Posts │ │Payments │ │Livestream│
    │  :5510 │ │ :5510 │ │ :5510 │ │:5510 │ │  :5510  │ │  :5510   │
    └────┬───┘ └───┬───┘ └───┬───┘ └──┬───┘ └────┬────┘ └─────┬────┘
         │         │         │        │           │            │
         └─────────┴─────┬───┴────┬───┴───────────┘            │
                         │        │                            │
                    ┌────▼───┐ ┌──▼────┐               ┌──────▼──────┐
                    │ Media  │ │ R18E  │               │ GetStream   │
                    │ :5510  │ │ :5510 │               │ Video+Chat  │
                    └────┬───┘ └───┬───┘               └─────────────┘
                         │        │
    ┌────────────────────┴────────┴──────────────────────┐
    │              Infrastructure Layer                    │
    │  SurrealDB │ Redis │ RabbitMQ │ GCS │ Secret Mgr   │
    └─────────────────────────────────────────────────────┘
```

**7 services deployed** to production (auth, events, posts, users, media, payments, livestream). R18E (recommendation engine) has a Dockerfile and test suite but is not yet in the Cloud Build pipeline.

---

## Technical Architecture

### Service Specifications

#### 1. Auth Service
- **Runtime**: Granian (Rust ASGI, uvloop, multi-threaded, dynamic workers via `$(nproc)`)
- **Auth flows**: Email/password (Argon2 hashing in SurrealDB), Google SSO (`google-auth`), Apple SSO (JWT verification)
- **JWT**: Shared secret distributed via Redis; auth service generates, others read
- **Credential storage**: AES-CBC envelope encryption — data encrypted with random DEK, DEK encrypted with KEK from Google Secret Manager
- **Rate limiting**: Redis + atomic Lua script, 3-window (per-minute/hour/day), by IP (SHA-256 of IP+User-Agent) or JWT user ID
- **KPI endpoint**: `GET /auth/kpis` — public, serves Prometheus + SurrealDB aggregate metrics for Grafana
- **GDPR**: Scheduled account deletion via K8s CronJob (daily at 02:00 UTC)

#### 2. Users Service
- **Social graph**: SurrealDB `friends` relation table with status enum (`pending | accepted | blocked | removed | rejected`)
- **Graph traversal**: `fn::find_relationships` up to 5 degrees of separation; `fn::exists_in_degree` for private event access
- **Blocking**: Separate `blocks` relation table
- **Notifications**: Novu integration (modular registry pattern) — friend request notifications on relationship creation

#### 3. Events Service
- **Geospatial**: `location.coordinates` stored as SurrealDB `Point` type; `fn::fetch_events_by_location` uses `geo::distance` filtering + pagination
- **Discovery feeds**: `fn::fetch_public_events`, `fn::fetch_trending_events` (score = attendees×3 + posts×2), `fn::fetch_private_events_for_user` (graph-gated)
- **Ticketing**: Multi-tier tickets (`ticket_tiers` table, capacity tracking, sold_count auto-incremented via SurrealDB `CREATE` event), unique ticket numbers (`TKT-XXXX-XXXX`)
- **Guestlists**: `guestlists` relation table for event invitations with invited-by tracking
- **WebSocket**: Real-time event updates (events service only)

#### 4. Posts Service
- **Data model**: `posts` is a SurrealDB relation table (`users → media`) with content, event association, and visibility flag
- **Comments**: `comments` relation table (`users → posts`)
- **Media**: File uploads validated then published to RabbitMQ for async processing by the media service
- **Content reporting**: Generic `_report_resource` for posts and comments, stored in `reports` table with status tracking

#### 5. Media Service
- **Pipeline**: RabbitMQ consumer (FastStream) → fetch from GCS temp → compress → extract metadata → upload final → update DB
- **Image processing**: Pillow + pillow-heif (HEIC/HEIF support), max 2048px, JPEG Q90, EXIF orientation correction, BlurHash generation for instant placeholders
- **Video processing**: FFmpeg async wrapper, H.264 CRF 21, 1080p max (1920×1080), 5Mbps bitrate cap, 12M buffer, 128k AAC audio, 44.1kHz sample rate; MOV→MP4 conversion
- **Thumbnails**: Auto-extracted at ~10% of video duration, uploaded as WebP alongside video
- **Storage**: Google Cloud Storage via obstore (Rust-based), with signed URL generation
- **Serialization**: ormsgpack (MessagePack) for RabbitMQ message encoding
- **Workers**: Granian with 1 worker (I/O-bound on FFmpeg), explicit `gc.collect()` after each processed file

#### 6. Payments Service
- **Providers**: Stripe (international markets) + Paystack (African markets)
- **Flows**: Payment intent → webhook verification → ticket creation → tier sold count increment → host notification (Novu) → buyer email
- **Webhook security**: Stripe signature verification, Paystack webhook validation
- **Split payments**: Paystack subaccount support for marketplace host payouts
- **PCI**: Level 1 compliant via Stripe tokenization

#### 7. Livestream Service
- **Provider**: GetStream.io (migrated from Cloudflare Stream)
- **Video SDK**: `getstream` Python SDK (sync, wrapped with `asyncio.to_thread` for non-blocking Quart)
- **Chat SDK**: `stream-chat` async SDK — one `livestream` channel per event, created alongside the video call
- **Flow**: Create call (backstage) → go-live (broadcast) → end-live (back to backstage) → end call (permanent)
- **Geofencing**: 1km radius check on `POST /scenes/<event_id>/attendee-location`, auto-promotes/demotes attendee ↔ viewer based on GPS
- **Tokens**: Unified Stream token covers both Video and Chat SDKs

#### 8. R18E Service (Recommendation Engine)
- **Status**: Developed and tested, **not yet deployed to production** (excluded from `cloudbuild.yaml`)
- **Approach**: SurrealDB native HNSW vector search — no external ML runtime (PyTorch deps are commented out in `requirements.txt`)
- **Algorithm**: Average ViT-768 media embeddings per event → HNSW KNN (top-100, EF=40) → cosine reranking → deduplication → future-event filter → preview cards
- **Stored functions**: `fn::fetch_similar_events` (full pipeline in SurrealQL), `fn::fetch_event_preview` (lightweight cards)
- **Workers**: Granian with 4 workers

### Shared Library (`shared/`)

| Module | Purpose |
|--------|---------|
| `microservice/client.py` | `MicroService` base class — SurrealDB pool, Redis, JWT, RabbitMQ, Prometheus, KPI aggregator |
| `microservice/enum.py` | `Microservice` StrEnum with `needs_rmq()` (media, posts, users, events) |
| `middleware/security.py` | CORS, HSTS, X-Frame-Options, CSP, content-type validation, request size limits (100MB) |
| `middleware/rate_limiter.py` | Redis + atomic Lua script, 3-window rate limiting (60/min, 1000/hr, 10000/day) |
| `middleware/validation.py` | File upload validation, input sanitization |
| `middleware/error_handler.py` | Centralized error handling with structured JSON responses |
| `kpi/` | `BusinessMetrics` (Prometheus), `KPIAggregator` (SurrealDB + Redis cache, 60s TTL), views |
| `workers/rmq/` | `RMQBroker` — FastStream RabbitMQ consumer, image/video compression, GCS upload, metadata extraction |
| `workers/novu/` | `NotificationManager` — modular registry pattern, typed notifications (OTP, welcome, friend request, event reminder, ticket purchase host, livestream, post interaction) |
| `workers/brevo/` | Brevo email client |
| `workers/resend/` | Resend email client |
| `workers/cloudflare_stream/` | Legacy Cloudflare livestream client (superseded by GetStream) |
| `workers/lsv1/` | Legacy livestream v1 client |
| `utils/crypto.py` | `EnvelopeCipher` — AES-CBC envelope encryption with Google Secret Manager KEK |
| `utils/paystack_client.py` | Paystack API wrapper (transactions, subaccounts, split payments) |
| `utils/veriff.py` | Veriff KYC/identity verification client |
| `utils/obstore.py` | GCS storage via obstore (Rust-based) |
| `utils/signer.py` | GCS signed URL generation for media delivery |
| `utils/apple_auth.py` | Apple SSO JWT token verification |
| `classful/` | `QuartClassful` — class-based views with route decorator |

### Technology Stack

| Layer | Technology | Details |
|-------|-----------|---------|
| **Language** | Python 3.13 | Async throughout (Quart ASGI) |
| **ASGI Server** | Granian | Rust-based, uvloop event loop, Rust task implementation, multi-threaded runtime |
| **Database** | SurrealDB v2 | Multi-model: graph relations, HNSW vector indexes (768-dim), geospatial `Point` + `geo::distance`, schemaless + schemafull tables, 17 stored functions, Argon2 hashing |
| **Connection Pool** | purreal | SurrealDB async pool manager (min/max connections, health checks, retry, max usage count) |
| **Cache** | Redis | JWT secret sharing, rate limiting (Lua scripts), KPI cache (60s TTL), aiocache decorator |
| **Message Queue** | RabbitMQ | Via FastStream library, ormsgpack serialization, media + r18e queues |
| **Object Storage** | Google Cloud Storage | Via obstore (Rust), signed URLs, temp → final upload pattern |
| **Payments** | Stripe + Paystack | Dual provider, webhook-driven, split payments |
| **Livestreaming** | GetStream.io | Video SDK (sync→async wrapped) + Chat SDK (native async) |
| **Notifications** | Novu | Modular typed notification system with auto-registry |
| **Email** | Brevo, Resend | Transactional email providers |
| **KYC** | Veriff | Identity verification sessions |
| **HTTP Client** | rusty-req, httpx | Rust-based async HTTP + Python httpx |
| **Serialization** | orjson, ormsgpack | Fast JSON (Rust) + MessagePack |
| **Monitoring** | Prometheus | Request count/latency/in-progress, DB/Redis latency histograms, business KPI counters/gauges |
| **Image Processing** | Pillow, pillow-heif, blurhash-python | Compression, HEIC/HEIF support, instant placeholders |
| **Video Processing** | FFmpeg (python-ffmpeg) | Async wrapper, H.264 CRF 21, 1080p, thumbnail extraction |
| **Security** | cryptography, PyJWT, bleach | AES-CBC envelope encryption, JWT, HTML sanitization |
| **Orchestration** | GKE (us-central1) | Docker multi-stage builds, non-root containers, port 5510 |
| **CI/CD** | Cloud Build + GitHub Actions | 9-stage pipeline, blue-green deploys, auto-rollback, Slack alerts |
| **Secrets** | Google Secret Manager | KEK storage for envelope encryption |

---

## Database Schema

SurrealDB schema (`init/schema.surql`) — 619 lines defining the full data model:

### Tables

| Table | Type | Key Fields |
|-------|------|-----------|
| `users` | Schemaless | first/last name, email, avatar, auth_provider (password/google/apple), stripe/paystack IDs, KYC status, `last_active`, `scheduled_deletion_at` |
| `credentials` | Schemafull | Envelope-encrypted data (encrypted_data, encrypted_decryption_key, IVs) linked to user |
| `leads` | Schemafull | Encrypted lead capture data |
| `events` | Schemaless | Title, description, price, location (`Point`), categories, host (record), attendee_count, duration, degree_of_freedom, HNSW text embeddings |
| `ticket_tiers` | Schemafull | Event-linked, name, price, capacity, `sold_count` (auto-incremented on ticket creation) |
| `tickets` | Schemafull | User or guest (email/name), event, tier, `ticket_number` (auto-generated `TKT-XXXX-XXXX`), `checked_in_at` |
| `scenes` | Schemafull | Livestream metadata (SRT, RTMP, WebRTC endpoints), event + user links |
| `posts` | Relation (users→media) | Content, event association, visibility, HNSW content embeddings |
| `comments` | Relation (users→posts) | Content |
| `friends` | Relation (users→users) | Status: `pending \| accepted \| blocked \| removed \| rejected` |
| `blocks` | Relation (users→users) | Unidirectional blocking |
| `attends` | Relation (users→events) | Unique per user-event, triggers `attendee_count` increment |
| `guestlists` | Relation (users→events) | Invitation tracking with `invited_by` and status |
| `has_media` | Relation (events→media) | Event media association |
| `media` | Schemaless | Content type (literal union), filename, status, metadata, thumbnail, blurhash, creator, HNSW 768-dim embeddings |
| `reports` | Schemaless | Reporter, reason, status, linked resource |

### SurrealDB Stored Functions (17 total)

Event discovery (`fetch_public_events`, `fetch_trending_events`, `fetch_events_by_location`, `fetch_private_events_for_user`), event detail (`fetch_event`, `fetch_event_preview`), ticketing (`fetch_user_tickets`), social graph (`create_relationship`, `get_friends`, `find_relationships`, `exists_in_degree`), guestlists (`fetch_event_guestlist`), posts (`fetch_post`), AI similarity (`fetch_similar_events`) — all computed server-side in SurrealQL.

---

## Infrastructure & Operations

### Deployment Architecture

- **Cloud Provider**: Google Cloud Platform
- **Compute**: GKE cluster (`backstage-cluster`, us-central1)
- **Registry**: Artifact Registry (`us-central1-docker.pkg.dev/.../scenes-backstage/`)
- **Build**: Cloud Build (E2_HIGHCPU_8 machine), parallel image builds for all 7 services, then rolling restart
- **Containers**: Docker multi-stage builds (test → prod), non-root user, port 5510
- **CronJob**: `scheduled-deletion-cleanup` — runs daily at 02:00 UTC for GDPR account deletion (512Mi–1Gi memory, 250m–500m CPU)

### CI/CD Pipeline

**Primary deploy** (production): `gcloud builds submit .` → Cloud Build (`cloudbuild.yaml`)

**Full GitHub Actions pipeline** (9 stages, `ci-test-deploy.yaml`):

```
Code Quality ──→ Unit Tests (matrix: 7 services) ──→ Integration Tests ──┐
                                                                          ├──→ Build Images ──→ Deploy Staging ──→ Smoke Tests + k6 ──→ Deploy Production (Blue-Green) ──→ Rollback (on failure)
                                                     Contract Tests ──────┘
```

| Stage | Tools | Details |
|-------|-------|---------|
| Code Quality | flake8, black, mypy | Syntax errors, formatting check, type checking (non-blocking) |
| Unit Tests | pytest (Docker matrix) | Per-service with SurrealDB + Redis + RabbitMQ in Docker, Codecov upload |
| Integration Tests | pytest + httpx | Full stack, all services running |
| Contract Tests | Postman CLI | API collection validation |
| Build | Docker Buildx | Multi-stage, layer caching, Artifact Registry push |
| Deploy Staging | kubectl set image | Namespace-isolated, rollout status wait (5m timeout) |
| Smoke Tests | pytest + k6 | HTTP endpoint validation + basic load test |
| Deploy Production | kubectl (blue-green) | Green deploy → canary health check → traffic swap → 5-min monitor |
| Rollback | kubectl patch | Auto-triggered on failure, Slack notification via webhook |

### Security

| Layer | Implementation |
|-------|---------------|
| **Authentication** | JWT (shared secret via Redis), Google SSO, Apple SSO |
| **Password Storage** | Argon2 (SurrealDB `crypto::argon2::generate`, hashed on CREATE/UPDATE events) |
| **Credential Encryption** | AES-CBC envelope encryption (random DEK per record, KEK from Secret Manager) |
| **Rate Limiting** | Redis + atomic Lua script, 3 windows (60/min, 1000/hr, 10000/day), per-IP or per-user |
| **Security Headers** | HSTS, X-Frame-Options DENY, X-XSS-Protection, X-Content-Type-Options nosniff, Referrer-Policy, Permissions-Policy |
| **CORS** | Configurable per environment (`partyscene.app`, `api.partyscene.app` in prod) |
| **Input Validation** | Content-Type enforcement, request size limits (100MB), bleach HTML sanitization |
| **Payment Security** | Stripe webhook signature verification, Paystack webhook validation, PCI DSS Level 1 (via Stripe) |
| **GDPR** | Scheduled account deletion CronJob, `scheduled_deletion_at` field on users |
| **KYC** | Veriff identity verification integration |

---

## Testing

### Test Suite

~200 test functions across 37 test files, covering all 8 services:

| Service | Test Files | Coverage |
|---------|-----------|----------|
| Auth | 6 (authentication, Apple SSO, rate limiting, security, token lifecycle, base) | Registration, login flows, SSO, token refresh/revocation |
| Events | 7 (creation, queries, updates, base, geospatial, live, pagination) | CRUD, geo search, trending, filtering |
| Users | 5 (base, management, relationships, blocking, privacy) | Social graph, friend requests, block enforcement |
| Posts | 2 (base, operations) | CRUD, comments, reporting |
| Media | 3 (base, operations, RabbitMQ consumer) | Upload pipeline, compression, metadata |
| Payments | 5 (base, operations, edge cases, idempotency, webhook security) | Stripe/Paystack flows, webhook verification |
| Livestream | 2 (base, management) | Stream lifecycle, permissions |
| R18E | 2 (base, operations) | Vector search, recommendations |
| Integration | 2 (auth-user flow, event creation flow) | Cross-service workflows |
| Security | 1 (SQL injection) | Injection prevention |
| Smoke | 1 (API endpoints) | Post-deploy health |

**Test infrastructure**: `docker-compose.test.yml` with SurrealDB (in-memory), Redis 7, RabbitMQ 3 — all with health checks.

**Load testing**: Locust framework (`tests/load_testing/locustfile.py`).

### Code Quality

- **Linting**: flake8 (syntax/logic errors), black (formatting)
- **Type checking**: mypy (configured via `pyproject.toml`, non-blocking in CI)
- **Input sanitization**: bleach for HTML, content-type enforcement, size limits

---

## KPI & Analytics

Built-in funding-grade metrics system — no external analytics dependencies:

### Real-time Counters (Prometheus)

Incremented at event success points across services:

| Metric | Service | Trigger |
|--------|---------|---------|
| `partyscene_signups_total` | Auth | OTP verification (register) |
| `partyscene_logins_total` | Auth | Password / Google / Apple login |
| `partyscene_events_created_total` | Events | Event creation |
| `partyscene_event_attendances_total` | Events | Attendance marking |
| `partyscene_ticket_purchases_total` | Payments | Stripe/Paystack webhook success |
| `partyscene_ticket_checkins_total` | Events | Ticket check-in |
| `partyscene_livestream_starts_total` | Livestream | Go-live |
| `partyscene_livestreams_active` (gauge) | Livestream | Inc on go-live, dec on end-live |
| `partyscene_posts_created_total` | Posts | Post creation |
| `partyscene_friend_requests_total` | Users | Friend request creation |

### Aggregate Metrics (SurrealDB → Redis cache, 60s TTL)

DAU/WAU/MAU (via `last_active` field), D1/D7/D30 retention cohorts, churn rate, signup growth (WoW/MoM), GMV, ARPU, ticket conversion rate, stickiness (DAU/MAU), plus time-windowed counts (24h/7d/30d signups, events, tickets, posts).

### Grafana Integration

`GET /auth/kpis` returns a flat JSON structure parseable by Grafana Infinity datasource with JSONata. `POST /auth/kpis/refresh` forces immediate recalculation. Setup guide: `docs/GRAFANA_KPI_SETUP.md`.

---

## API

### REST API
- **Documentation**: [Postman Workspace](https://scenes-dev.postman.co/workspace/Scenes-Dev-Space~3e844513-40dc-4bc3-812b-829c5d5e37a3)
- **Authentication**: JWT Bearer tokens
- **Rate Limiting**: 60/min, 1000/hr, 10000/day (configurable per-endpoint)
- **Response Format**: JSON via `api_response()` / `api_error()` helpers with consistent status codes

### WebSocket
- Events service only — real-time event updates via Quart WebSocket routes

---

## Getting Started

### Prerequisites
- Python 3.13
- Docker & Docker Compose
- Google Cloud SDK (for production)

### Local Development
```bash
# Clone repository
git clone https://github.com/PartyScene/backstage.git
cd backstage

# Copy environment config
cp .env.example .env
# Fill in: SURREAL_URI, REDIS_URI, RABBITMQ_URI, GCS_BUCKET_NAME, etc.

# Start infrastructure + services
docker network create cloudbuild
docker-compose up -d

# Run tests (per service)
docker-compose -f docker-compose.test.yml up -d rabbitmq surrealdb redis
docker-compose -f docker-compose.test.yml run --rm microservices.auth

# Access
# SurrealDB: http://localhost:8000
# RabbitMQ Management: http://localhost:15672
```

### Production Deployment
```bash
# Connect to GKE cluster
gcloud container clusters get-credentials backstage-cluster \
  --zone us-central1 --project partyscene-441317

# Build and deploy all services (Cloud Build)
gcloud builds submit .

# Check status
kubectl get pods
kubectl logs -l app=auth --tail=100
```

### Developer Documentation
- [Installation Guide](./docs/INSTALLATION.md)
- [Quick Start Testing](./docs/QUICK-START-TESTING.md)
- [CI/CD Implementation Guide](./docs/CI-CD-IMPLEMENTATION-GUIDE.md)
- [Cloud Build Guide](./docs/CLOUDBUILD.md)
- [Windows Testing Guide](./docs/RUN-TESTS-WINDOWS.md)
- [Grafana KPI Setup](./docs/GRAFANA_KPI_SETUP.md)
- [API Documentation](https://scenes-dev.postman.co/workspace/Scenes-Dev-Space~3e844513-40dc-4bc3-812b-829c5d5e37a3)

---

## Roadmap

### Phase 1: MVP Launch (October 2025) ✅
- ✅ User registration and authentication (email/password, Google SSO, Apple SSO)
- ✅ Event creation with geospatial discovery and trending algorithm
- ✅ Multi-tier ticketing with Stripe + Paystack payments
- ✅ Media pipeline (image/video compression, thumbnails, BlurHash)
- ✅ Live streaming with GetStream.io (Video + Chat)
- ✅ Social features (friends, blocks, posts, comments, guestlists)
- ✅ Notification system (Novu — OTP, welcome, friend requests, event reminders, ticket purchases)
- ✅ KPI tracking system with Grafana integration
- ✅ Mobile apps (iOS & Android) released

### Phase 2: Growth & Optimization (Q4 2025)
- 🔄 Deploy R18E recommendation engine to production
- 🔄 Push notifications via Novu mobile channels
- 🔄 Event analytics dashboard for organizers
- 🔄 Enhanced content discovery feeds
- **Target**: 5,000 MAU, $5K MRR

### Phase 3: Monetization Expansion (Q1 2026)
- 📅 Premium organizer subscriptions ($29/month)
- 📅 Business accounts for venues ($99/month)
- 📅 Promotional features and sponsored listings
- 📅 Advanced analytics and reporting
- **Target**: 25,000 MAU, $25K MRR

### Phase 4: Scale (Q2 2026)
- 📅 API integrations for third-party platforms
- 📅 Advanced streaming (multi-camera, RTMP ingest)
- 📅 Enterprise security and compliance tooling
- 📅 ML-powered content moderation (r18e expansion)
- **Target**: 100K+ MAU, $100K+ MRR

---

## Business & Market

### Revenue Streams
1. **Transaction Fees**: 3-5% on paid event tickets (Stripe + Paystack, dual-market coverage)
2. **Premium Subscriptions**:
   - Organizer Pro: $29/month (enhanced analytics, promotion)
   - Business: $99/month (multi-venue management, API access)
3. **Promotional Features**:
   - Featured event listings: $50-200
   - Targeted advertising: CPM-based
4. **Data Services**: Anonymized event trend reports for businesses

### Unit Economics (Projected)
- **CAC** (Customer Acquisition Cost): $8-12
- **LTV** (Lifetime Value): $45-60 per user
- **LTV:CAC Ratio**: 4.5:1 (target)
- **Break-even**: Projected 18-24 months

### Market Position

| Feature | PartyScene | Eventbrite | Meetup | Facebook Events |
|---------|-----------|-----------|--------|----------------|
| Geospatial Discovery | ✅ SurrealDB geo queries | ❌ | ⚠️ Basic | ❌ |
| AI Recommendations | ✅ HNSW vector similarity | ❌ | ❌ | ⚠️ Basic |
| Integrated Livestreaming | ✅ GetStream Video + Chat | ❌ | ❌ | ⚠️ Facebook Live |
| Social Graph | ✅ 5-degree traversal | ❌ | ⚠️ Basic | ✅ Native |
| Multi-Tier Ticketing | ✅ Capacity tracking | ✅ | ⚠️ Limited | ❌ |
| Dual Payment Providers | ✅ Stripe + Paystack | ✅ Stripe only | ⚠️ Limited | ❌ |
| Real-time KPI Dashboard | ✅ Prometheus + Grafana | ❌ | ❌ | ❌ |
| Geofenced Livestream Roles | ✅ GPS-based auto-promote | ❌ | ❌ | ❌ |

**Key Advantage**: Only platform combining HNSW vector recommendations, geospatial event discovery, integrated livestreaming with geofenced roles, and dual-market payments (Stripe + Paystack) in a single social events ecosystem.

### Traction
- **Launch**: October 17, 2025 (iOS & Android)
- **Waitlist**: 50+ users (pre-launch, minimal marketing)
- **Social**: 89 Instagram followers (organic growth)
- **Product Hunt**: Projected top 10-15 for launch day

---

## Investment Opportunity

### Funding Stage
**Seed Round**: Seeking $1-2M to accelerate product development and market entry

### Use of Funds
- **Product Development** (40%): R18E deployment, enhanced features, UX improvements
- **Marketing & Growth** (35%): User acquisition, partnerships, Africa market expansion
- **Infrastructure** (15%): Scaling, monitoring, security hardening
- **Team Expansion** (10%): Frontend developers, product manager

### 18-Month Milestones
- **Month 6**: 10K users, 1K events created, R18E recommendations live
- **Month 12**: 50K users, $50K MRR
- **Month 18**: 150K users, $200K MRR, break-even trajectory

---

## Technical Leadership

### Development Philosophy
- **Performance-first**: Rust-based ASGI server (Granian), Rust JSON (orjson), Rust HTTP (rusty-req), Rust storage (obstore) — zero-overhead Python where it matters
- **Database as application layer**: 17 SurrealDB stored functions replace thousands of lines of application ORM code — graph traversal, trending scores, geo queries, vector similarity, and ticket management all computed server-side
- **Security in depth**: Envelope encryption for PII, Argon2 at the database level, atomic Lua-based rate limiting, webhook signature verification, GDPR deletion automation
- **Observable from day one**: Prometheus counters wired at every business event, SurrealDB aggregate KPIs, Grafana-ready endpoint — investor metrics without third-party analytics

### Expertise
- Backend Engineering: Python microservices, async architecture, Rust toolchain integration
- Cloud Infrastructure: GCP, Kubernetes, Docker, Cloud Build production pipelines
- Databases: SurrealDB (graph, vector, geo), Redis, connection pooling
- DevOps: 9-stage CI/CD, blue-green deploys, automated rollback
- Payments: Dual-provider integration (Stripe + Paystack), webhook-driven architecture

---

## Repository & Contact

**Repository**: [GitHub - PartyScene/backstage](https://github.com/PartyScene/backstage)
**API Docs**: [Postman Workspace](https://scenes-dev.postman.co/workspace/Scenes-Dev-Space~3e844513-40dc-4bc3-812b-829c5d5e37a3)
**Status**: Production, actively deployed on GKE
**License**: Proprietary software. All rights reserved.
