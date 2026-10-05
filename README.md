# Latch — BFC AI Service

A FastAPI microservice that powers **Latch**, the streaming AI assistant for [Balisong Flipping Center](https://github.com) (BFC) — a community platform for balisong (butterfly knife) flipping enthusiasts.

Latch answers questions about the site, balisong flipping, and specific knives/makers, and can search posts, look up profiles, browse public collections, and file content reports — all through live tool calls against the BFC backend API, never from memory alone.

## How it works

- **Model access:** [Anthropic's Claude](https://www.anthropic.com/claude) via **AWS Bedrock's Converse API** (`boto3` `bedrock-runtime` client, `converse_stream`). Not a direct call to Anthropic's Messages API — Bedrock wraps the same model behind AWS's own request/response shape and IAM-based auth.
- **Streaming:** the Bedrock response is a stream of content-block deltas; `stream_chat()` in `app/bedrock_client.py` accumulates them into text and tool-use blocks and yields text as it arrives, forwarded to the client as a chunked `StreamingResponse`.
- **Conversation history:** kept per `session_id` across turns (`app/sessions.py`), persisted in Redis with a 24-hour TTL — survives restarts and is shared across instances. Before each request the history is trimmed to the last `MAX_HISTORY_TURNS` user turns (cut only at user-typed messages, so a tool call is never separated from its result), and tool results from earlier turns are replaced with a placeholder — the assistant's own reply already summarizes them, and raw results (e.g. 20 posts from `search_posts`) are the bulk of input tokens.
- **System prompt:** the frozen persona/tone/site-navigation rules live in `SYSTEM_PROMPT_TEMPLATE` (`app/prompts.py`), byte-identical on every request. The per-request variables — the user's current page and whether they're logged in — come from `build_request_context()`, sent as a separate trailing block rather than interpolated into the template, so it never invalidates the cache below.
- **Prompt caching:** `bedrock_client.py` sends `system` as `[frozen prompt, cachePoint, request context]` on every turn, so the frozen block (plus `tools`, which chains ahead of it) is read from cache instead of billed at full price after the first request. Bedrock's minimum cacheable prefix is model-dependent — 4,096 tokens for Claude Haiku 4.5, the model this service currently uses — and `tools` + the frozen prompt currently come to ~4,300 tokens, so it activates (~4,300 cache-read tokens per call); verify via the `cacheReadInputTokens`/`cacheWriteInputTokens` fields logged from the Converse stream's `metadata` event, don't assume from the code alone.
- **Tool calling:** `app/tools.py` declares the tool specs (`search_posts`, `get_account_profile`, `get_collection`, `search_knife_catalog` — free-text plus blade/handle material, pivot system, and max-price filters — `get_knife_details`, `get_maker_details`, and — for logged-in sessions only — `report_content`) and dispatches them. Each tool calls out to the real BFC backend via `app/backend_client.py` (an `httpx` client). This is genuine function calling: Claude decides when to call a tool, gets real results back, and continues the response — not prompt-stuffed retrieval.
- **Error handling:** `backend_client.py` wraps every backend call in `try/except` for `httpx.HTTPStatusError` and `httpx.RequestError` (including timeouts, on a 10s client timeout) and returns the error back to the model as a tool result, so a failed lookup becomes something Claude can talk around instead of a crash. The Bedrock client (`bedrock_client.py`) retries throttling/service-unavailable errors up to 3 times with exponential backoff before falling back to a plain-text error yielded to the client.
- **Auth:** `POST /chat/stream` requires an `X-Internal-Secret` header matching `AI_SERVICE_SHARED_SECRET`, sent by the backend on every relayed call. The check is skipped when the secret is unset (local dev).

## Project layout

```
app/
  main.py            FastAPI app, mounts the chat router
  config.py           Settings (env-driven)
  prompts.py           System prompt template
  bedrock_client.py    Streaming chat loop + Bedrock Converse calls
  tools.py             Tool specs + dispatch
  backend_client.py    HTTP client for the BFC backend API
  sessions.py          Redis-backed conversation history
  routers/chat.py      POST /chat/stream endpoint
tests/                 Pytest suite (respx for HTTP, fakeredis for sessions)
evals/
  cases.yaml           Eval cases and their pass criteria
  run.py               Eval runner (real model, live read-only API)
  reports/             Generated pass-rate reports
```

## Setup

**Prerequisites**
- Python 3.13
- An AWS account with Bedrock model access enabled for the Claude model you intend to use, in the target region
- AWS credentials available locally (see [Credentials & swapping the model](#credentials--swapping-the-model) below)
- A running instance of the BFC backend API (or any API matching the endpoints `backend_client.py` calls)
- A running Redis instance (e.g. `docker run -p 6379:6379 redis:7-alpine`) for conversation history

**Steps**

```bash
git clone <this-repo>
cd ai-service

python -m venv venv
source venv/Scripts/activate   # Windows (Git Bash); use venv/bin/activate on macOS/Linux

pip install -r requirements.txt

cp .env.example .env
# edit .env — see Environment variables below

uvicorn app.main:app --reload --port 8001
```

`dev.sh` is a convenience script for local development that also brings up the BFC backend (Docker Compose) and frontend (`npm run dev`) alongside this service, so all three run together. `restart-backend.sh` and `stop.sh` are the matching backend-only restart/stop helpers. These three scripts are tuned to one local machine's paths and ports — treat them as a reference, not something to run as-is elsewhere.

Health check: `GET /health` → `{"status": "ok"}`

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

63 tests covering every module. No real AWS or Redis needed — Bedrock calls are mocked directly (`unittest.mock` on the `boto3` client; moto doesn't support `bedrock-runtime`'s `converse_stream` well), backend HTTP calls are mocked with `respx`, and the Redis-backed session store is swapped for `fakeredis` in tests via `conftest.py`. Both deploy pipelines run this suite as a required gate before building/pushing/deploying.

## Evals

Unit tests prove the code does what it was written to do; evals measure whether Latch actually gives good answers. `evals/run.py` runs every case in `evals/cases.yaml` against the real model (3 runs each by default, to expose inconsistency), with tools hitting the live, read-only BFC API — except `report_content`, which is stubbed for logged-in sessions so an eval run can never file a real report (logged out, Latch's own guard rejects it before any backend call). Sessions use an in-memory `fakeredis`, so nothing else needs to be running.

```bash
pip install -r requirements-dev.txt
python -m evals.run                 # full suite, 3 runs per case
python -m evals.run --runs 1 --case report   # quick filtered run
```

Each case is graded on the final turn by deterministic checks — required/forbidden tool calls, required tool arguments (e.g. `post_type` contains `TRICK_TUTORIAL`), no tool call returning an error, and required/forbidden text in the reply — plus, for qualitative behavior (no hallucinated specs, correct logged-out reporting guidance, tone), a rubric graded by a stronger model (Claude Sonnet 4.6 on Bedrock, forced to return a structured pass/fail verdict). Each run writes `evals/reports/<timestamp>.md` (pass rate overall, by category, and by case with failure reasons, plus tokens, latency, and estimated cost) and a matching `.json` with full transcripts.

Evals aren't part of CI: they cost money, results vary run to run, and the deploy role has no Bedrock access.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `AWS_REGION` | `us-east-1` | AWS region for the Bedrock client |
| `BEDROCK_MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Bedrock model ID to invoke |
| `BACKEND_BASE_URL` | `http://localhost:8080/api` | Base URL of the BFC backend API that the tools call |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis instance used to persist conversation history |
| `AI_SERVICE_SHARED_SECRET` | `""` | Shared secret the backend sends as `X-Internal-Secret`; auth is skipped if unset |
| `MAX_HISTORY_TURNS` | `10` | Number of most recent user turns kept in conversation history |

Defined in `app/config.py` via `pydantic-settings`, loaded from `.env`.

## Credentials & swapping the model

This service authenticates to AWS the standard `boto3` way — there's no API key value stored in `.env`. Credentials come from whatever the default credential chain finds: an AWS CLI profile (`~/.aws/credentials`), environment variables (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN`), or an IAM role if deployed on AWS compute (EC2/ECS/Lambda). To run this under a different AWS account, swap whichever of those the deployment environment uses — no code changes required. The IAM identity needs `bedrock:InvokeModelWithResponseStream` (or the Converse-API equivalent) permission on the target model.

To point at a different Claude model on Bedrock, change `BEDROCK_MODEL_ID` in `.env` — nothing else needs to change.

To swap from Bedrock to Anthropic's direct Messages API instead, the change is scoped to `app/bedrock_client.py`: replace the `boto3` `bedrock-runtime` client with the `anthropic` SDK's `client.messages.stream(...)`. The request/response shapes differ (Bedrock's Converse API vs. Anthropic's Messages API), but the streaming tool-use loop — accumulate content-block deltas, detect a `tool_use` stop reason, execute the tool, append the result, continue the loop — carries over directly; `app/tools.py` and `app/backend_client.py` wouldn't need to change at all.

## API

**`POST /chat/stream`**

Request body:

```json
{
  "session_id": "some-session-id",
  "message": "what's the krake raken like?",
  "access_token": null,
  "current_path": "/product-world"
}
```

- `access_token` — optional; when present, gates access to the `report_content` tool and is forwarded as the `Authorization` header on backend calls that need it.
- `current_path` — optional; the page the user is currently on, used to tailor the system prompt's guidance.

Response: `text/plain` streamed chunks of the assistant's reply, as they're generated.

## Known limitations

- **Catalog data isn't fully verified yet.** Only the Squid Industries entries have been fact-checked against official/retailer sources; Squidtrainer and Mako still need the same pass.
- **`X-Internal-Secret` is a shared static secret**, not per-caller or rotatable without a redeploy of both sides. Fine for the current backend-to-AI-service trust boundary; wouldn't scale to more callers without per-client keys.

## CI/CD

`dev`, `test`, and `main` are all branch-protected — every change goes through a PR, and merging requires the `Pytest` status check to pass. Direct pushes, including from repo admins, are rejected.

Two deploy pipelines, each with its own required test job that must pass before the build/push/deploy job runs:

- **`test`** (`.github/workflows/deploy-ai-service-to-test.yml`) — runs pytest, then builds the Docker image, pushes to the testing ECR repo, and deploys via AWS SSM `RunShellScript` to the same EC2 host the backend and frontend testing environments run on.
- **`main`** (`.github/workflows/deploy-ai-service-to-prod.yml`) — same test gate, then builds and deploys to production the same way. Both authenticate to AWS via GitHub OIDC.

`.github/workflows/tests.yml` runs the same suite independent of deploy, on pushes to `dev` and PRs into `main`/`dev`/`test`.

Promote staging to production by merging `test` into `main`.

## Related

- [BalisongFlippingCenterServer](https://github.com/BalisongFlippingCenter/BalisongFlippingCenterServer) — Spring Boot backend; proxies chat requests here from `/ai/**`
- [BalisongFlippingCenterWeb](https://github.com/BalisongFlippingCenter/BalisongFlippingCenterWeb) — React/TypeScript frontend; the chat widget users actually talk to
