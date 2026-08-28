# Local production-shaped development runbook

This runbook starts the real API-mode MOSAIC demonstration. It does not use the
frontend Demo store or a mock Provider.

## 1. Current device prerequisites

The verified Windows setup uses:

- Node.js 24 and pnpm 11
- Python 3.12 and uv
- PostgreSQL 18.6 on `127.0.0.1:5432`
- Redis 8.10 on `127.0.0.1:6379`
- Erlang 28.4 and RabbitMQ 4.3 on `127.0.0.1:5672`
- a Beijing-region Bailian API key

PostgreSQL and RabbitMQ are user-level development processes on this device,
not Windows services. Confirm them before starting the application:

```powershell
$pgIsReady = (Get-Command pg_isready -ErrorAction Stop).Source
& $pgIsReady -h 127.0.0.1 -p 5432
redis-cli ping
rabbitmq-diagnostics -q ping
```

Expected results are `accepting connections`, `PONG` and `Ping succeeded`.

## 2. Load device secrets

Run this in every backend process shell. It reads user-scoped values without
printing them:

```powershell
$env:DASHSCOPE_API_KEY = [Environment]::GetEnvironmentVariable('DASHSCOPE_API_KEY', 'User')
$env:MOSAIC_SESSION_TOKEN_PEPPER = [Environment]::GetEnvironmentVariable('MOSAIC_SESSION_TOKEN_PEPPER', 'User')
$env:MOSAIC_LIVE_EVIDENCE_HMAC_KEY = [Environment]::GetEnvironmentVariable('MOSAIC_LIVE_EVIDENCE_HMAC_KEY', 'User')

if ([string]::IsNullOrWhiteSpace($env:DASHSCOPE_API_KEY)) { throw 'Missing DASHSCOPE_API_KEY' }
if ([string]::IsNullOrWhiteSpace($env:MOSAIC_SESSION_TOKEN_PEPPER)) { throw 'Missing MOSAIC_SESSION_TOKEN_PEPPER' }
```

Never echo these values, put them in `apps/api/.env`, pass them on a command
line or commit a live evidence JSON.

## 3. Set local non-secret configuration

```powershell
$env:APP_ENVIRONMENT = 'development'
$env:DATABASE_URL = 'postgresql+asyncpg://mosaic:mosaic@127.0.0.1:5432/mosaic'
$env:REDIS_URL = 'redis://127.0.0.1:6379/0'
$env:RABBITMQ_URL = 'amqp://mosaic:mosaic@127.0.0.1:5672/'
$env:SESSION_COOKIE_SECURE = 'false'
$env:AUTH_REGISTRATION_ENABLED = 'false'
$env:AUTH_ALLOWED_ORIGINS = '["http://127.0.0.1:3000","http://localhost:3000"]'
```

The `mosaic:mosaic` database and RabbitMQ credentials are local-development
credentials only. Production settings reject them, reject loopback origins and
require secure cookies plus `amqps://`.

On this device the Beijing Provider endpoints work while Clash/Mihomo is in
rule mode, where the existing `aliyuncs.com` rule is direct. Global mode caused
TLS connection failures. This is a device networking constraint, not an
application fallback.

## 4. Initialize durable state

```powershell
pnpm migrate:api
pnpm seed:catalog
pnpm smoke:rabbitmq
```

The normal catalog seed is deliberately fail-closed: routes start degraded and
disabled. To activate the four tested routes, first run the chargeable real
Provider gate from a clean committed tree. The evidence HMAC key must be at
least 32 non-placeholder characters and is never written into the evidence:

```powershell
$evidencePath = Join-Path ([System.IO.Path]::GetTempPath()) 'mosaic-bailian-live-evidence.json'
if ([string]::IsNullOrWhiteSpace($env:MOSAIC_LIVE_EVIDENCE_HMAC_KEY)) { throw 'Missing MOSAIC_LIVE_EVIDENCE_HMAC_KEY' }
uv run --project apps/api python apps/api/scripts/provider_smoke.py `
  --live --output $evidencePath
if ($LASTEXITCODE -ne 0) { throw 'Live Provider gate failed; routes remain disabled' }

uv run --project apps/api python apps/api/scripts/seed_product_catalog.py `
  --activate --live-evidence-file $evidencePath
```

Bind the tenant-scoped Qwen3-TTS resources after the base routes are active.
The first run creates real VoiceDesign and CustomVoice resources and therefore
requires explicit charge confirmation:

```powershell
uv run --project apps/api python apps/api/scripts/provision_demo_voice_resources.py `
  --tenant mosaic-demo --confirm-provider-charges
```

After both bindings are active, rerunning without the confirmation flag is
idempotent and makes no Provider calls. A paid revalidation must specify both
`--revalidate --confirm-provider-charges`. Provider voice IDs stay in the tenant
entitlement JSON and are never printed, committed, or accepted through the
public generation request.

`Qwen3-TTS 1.7B Base` has no current Bailian hosted execution route. It remains
an internal historical identity, is marked `unsupported`, and is omitted from
the customer catalog rather than aliased to Flash.

Activation requires the exact expected model IDs, all four modalities, Provider
request-ID presence, usage presence and non-empty media artifacts. A skipped,
mocked, partial or older-than-24-hours result is rejected.

Create the invitation-only demo account through the protected operator CLI.
It emits a 24-hour one-time credential and can grant the local PTS balance in
the same audited transaction:

```powershell
uv run --project apps/api python apps/api/scripts/operator_accounts.py create `
  --account 'demo@mosaic.local' --tenant-slug 'mosaic-demo' --tenant-name 'MOSAIC Demo' `
  --role owner --initial-points-minor 100000 `
  --operator-subject 'local-operator' --reason 'local staging bootstrap'
```

Deliver the printed credential out of band, then complete the forced password
change in the browser. Production never auto-creates a default account.

## 5. Start the durable execution stack

Use five backend terminals, each with sections 2 and 3 loaded:

```powershell
pnpm relay:chat
```

```powershell
pnpm relay:generation
```

```powershell
pnpm worker:chat
```

```powershell
pnpm worker:generation
```

```powershell
pnpm worker:generation:video
```

The two relays publish fenced outbox rows by event type. The chat, media
generation and video generation consumers load authoritative data from
PostgreSQL, reserve billing, call Bailian and persist results. The media and
video consumers publish independent Redis heartbeats only after their
dependencies are ready.

## 6. Start API and Web

After all five durable processes are ready, start the API with submissions
enabled:

```powershell
$env:CHAT_SUBMISSION_ENABLED = 'true'
$env:GENERATION_SUBMISSION_ENABLED = 'true'
pnpm dev:api
```

Start the Web application in another terminal:

```powershell
$env:NEXT_PUBLIC_MOSAIC_SERVICE_MODE = 'api'
$env:NEXT_PUBLIC_MOSAIC_SKIP_LOGIN = 'true' # local development only
pnpm dev:web
```

`NEXT_PUBLIC_MOSAIC_SKIP_LOGIN` only enables a local development convenience:
the Web server reads the device-scoped demo credentials, calls the real API
login endpoint, and forwards the resulting session cookies. It is disabled in
production builds and does not make any backend endpoint anonymous.

Open <http://127.0.0.1:3000>. The production-shaped shell intentionally does
not display internal service-mode or demo-tenant labels.

Before submitting chargeable work, verify the hard gate:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/health/ready'
```

It must return `status: ready`. A live API process alone is insufficient: the
gate also requires PostgreSQL, Redis, the Provider credential, both relays and
the chat, media and video workers.

## 7. Verification

```powershell
pnpm verify:api
pnpm verify:web
pnpm test:e2e
```

The Playwright suite deliberately exercises the deterministic Demo mode for
visual and interaction regression. Real acceptance additionally requires a
browser/API run that creates new chat and media jobs and confirms their rows,
queue consumption, usage, artifact download and Provider identity.

Run the redacted full-stack gate against the live local API:

```powershell
$env:MOSAIC_DEMO_EMAIL = [Environment]::GetEnvironmentVariable('MOSAIC_DEMO_EMAIL', 'User')
$env:MOSAIC_DEMO_PASSWORD = [Environment]::GetEnvironmentVariable('MOSAIC_DEMO_PASSWORD', 'User')
uv run --project apps/api python apps/api/scripts/full_stack_live_smoke.py `
  --base-url http://127.0.0.1:8000 --tenant mosaic-demo `
  --confirm-provider-charges
```

The gate fails if any catalog item is not executable, or if text, image,
video, Flash, VoiceDesign, or CustomVoice fails to return a real response or
artifact.

## 8. External production gates still required

- Use operator-managed PostgreSQL/Redis/RabbitMQ/S3 endpoints, TLS and secret injection.
- Generate the current commit's signed live evidence before activating Provider routes.
- Pass built-image startup/digest, capacity, fault and rollback drills on the release host.
- Add payment/invoice integration before treating internal PTS as a commercial tariff.
- Add the organization-specific MFA, tenant administration and support procedures required
  by the intended customer and compliance scope.
