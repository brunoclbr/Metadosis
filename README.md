# Metadosis: From Greek *metádosis* (μετάδοσις), “transmission” or “imparting”

> **Capture how experts think. Turn it into guidance for the next person.**

Metadosis is an AI Apprentice that watches and listens while an expert works, asks *why* at the moments that matter, and turns tacit judgment into a structured, citable **Work Map**. Later, it uses that captured knowledge to coach a learner through a new case—without pretending to know what the expert never taught it.

The system combines a real-time ElevenLabs voice agent, independent screen and camera context, evidence-grounded knowledge distillation, PostgreSQL, and an optional Neo4j projection.

## How it works

```text
EXPERT                                                    LEARNER
  │                                                          │
  │ voice + screen/camera                                    │ voice + live screen/camera
  ▼                                                          ▼
Observe → ask why → debrief → teach back               Load Work Map → coach → review
  │                                                          ▲
  └──────────── confirmed, citable evidence ─────────────────┘
                         │
                    PostgreSQL
                  source of truth
                         │
                optional projection
                         ▼
                       Neo4j
```

### 1. Learn from an expert

The Apprentice stays close to the work, asks grounded questions about decisions, exceptions, thresholds, and guardrails, then teaches its understanding back for correction. Only confirmed knowledge becomes a Work Map.

### 2. Preserve source truth

Expert sessions persist transcript-backed claims and confirmed visual observations as citable evidence. PostgreSQL remains authoritative even if a downstream graph projection fails.

### 3. Coach the next person

In teaching mode, the agent loads the selected Process through the authenticated teacher-context endpoint, coaches from the captured expert logic, and reviews the learner's case. Learner observations are live-only and are **never written back** into the Work Map.

## Visual intelligence, with boundaries

Screen and camera are independent inputs. Each is enabled explicitly by the user and is never opened before its button is pressed.

| Input | Browser API | Sampling | Why |
|---|---|---:|---|
| Screen | `getDisplayMedia` | Every 0.5s | Screens are mostly static, so small changes can matter. |
| Camera | `getUserMedia` (front camera) | Every 4s, with a 6s cooldown | Camera pixels move constantly; the coarse comparison only decides what is worth analyzing. |

Both inputs use the same endpoint, vision model, and event shape, distinguished by `source: "screen" | "camera"`. Raw frames are never stored; only the model's one-sentence observation is retained where the session policy permits it.

- **Expert session:** confirmed observations may become citable Work Map evidence.
- **Teaching session:** observations are supplied as live coaching context and deliberately not persisted.

This boundary prevents a learner's actions from being mistaken for expert knowledge.

## Architecture

| Layer | Responsibility |
|---|---|
| `frontend/` | Next.js workspace, voice session lifecycle, screen/camera capture, and server-only ElevenLabs token minting. |
| `src/domain/` | Framework-independent knowledge and provenance contracts. |
| `src/agent/` | LangGraph state and orchestration. |
| `src/app/backend/api/` | Thin FastAPI adapters for health, chat, visual observations, Brain APIs, and webhooks. |
| `src/app/backend/services/` | Brain ingestion and knowledge-graph projection. |
| `src/app/clients/` | PostgreSQL, Neo4j, and external client integrations. |

### Storage model

**PostgreSQL is the product source of truth.** It stores Processes, training sessions, raw transcripts, structured knowledge documents, visual observations, temporal provenance, and graph-projection status. The backend applies the idempotent Brain schema at startup.

**Neo4j is an optional, real projection—not a stub.** When `NEO4J_URI`, `NEO4J_USERNAME`, and `NEO4J_PASSWORD` are configured, the async driver initializes constraints and indexes, projects completed Work Maps with Cypher, and supports graph queries for workflows, guardrails, decisions, exceptions, and supporting evidence. If Neo4j is unavailable or unconfigured, capture remains operational and PostgreSQL stays authoritative.

**pgvector is not implemented.** The domain exposes a graph-first `vector_scope()` seam for a future retriever, but the current schema contains no vector extension, embedding column, or similarity query.

## Voice-agent workflow

The browser supplies three initiation variables: `session_mode`, `process_id`, and `greeting`.

```text
START
  └─ Mode Router (silent)
      ├─ learning
      │   Capture Task 1 → Capture Task 2 → Debrief Offer
      │          ↑              │                ├─ continue ──┘
      │          └── Off Record ┘                └─ Debrief
      │                                               ↓
      │                                          Teach-back → Sign Off → End
      │
      └─ teaching
          Load Expert Knowledge → Tutor → Tutor Review → Sign Off → End
```

The deployed voice agent currently defines:

- Agent ID `agent_4901m41mp1zge0ha18wcdzp853wn`
- Gemini 3.8 Flash at temperature `0.2`
- Scribe Realtime ASR
- Eleven v3 Conversational TTS with Expressive Mode
- a 30-minute maximum conversation duration
- the `skip_turn` system tool
- the `load_expert_knowledge` webhook tool

## Local development

### Requirements

- Python `>=3.12,<3.14`
- [`uv`](https://docs.astral.sh/uv/)
- Node.js `>=20.9`
- Docker
- microphone permission; camera and screen permission for the corresponding visual inputs

### Start the stack

Copy the environment template and replace provider placeholders. The PostgreSQL defaults match Docker Compose:

```bash
cp .env.example .env
```

Start PostgreSQL 16 with persistent local storage:

```bash
docker compose up -d postgres
```

Start the backend. It applies the idempotent Brain MVP schema on startup:

```bash
make run-backend
```

Install and start the frontend in another terminal:

```bash
make frontend-install
make run-frontend
```

The application is then available at `http://localhost:3000`; the API runs at `http://localhost:8000`.

> [!NOTE]
> The root `.env.example` expected by the command above is not present in every checkout. If it is absent, create `.env` with the required names listed below; never copy secrets from another environment into source control.

### Relevant checks

```bash
make format-check
make lint-check
make frontend-check
uv run pytest tests/test_teacher_context.py
```

Run only the focused tests relevant to your change; there is intentionally no Make target that runs the entire Python suite.

## Environment variables

Values are intentionally omitted. Secrets must remain server-side.

### Backend

```text
MODEL_PROVIDER
MODEL_NAME
OPENAI_API_KEY
ANTHROPIC_API_KEY
GEMINI_API_KEY
COMET_API_KEY
ELEVENLABS_API_KEY
ELEVENLABS_VOICE_ID
ELEVENLABS_MODEL_ID
ELEVENLABS_WEBHOOK_SECRET
TEACHER_CONTEXT_SECRET
BRAIN_EVIDENCE_SETTLEMENT_SECONDS
COMET_PROJECT
OPIK_CONFIG_PATH
MONGODB_CONNECTION_STRING
DATABASE_URL
NEO4J_URI
NEO4J_USERNAME
NEO4J_PASSWORD
NEO4J_DATABASE
```

### Frontend server

`ELEVENLABS_API_KEY` and `ELEVENLABS_AGENT_ID` are read only by `frontend/app/api/elevenlabs/session/route.ts`, which mints a short-lived conversation token. They must **not** use the `NEXT_PUBLIC_` prefix.

### Local PostgreSQL

Docker Compose accepts `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_PORT`, with local `metadosis` defaults.

## Webhooks and authenticated context

### ElevenLabs post-call webhook

```text
POST http://127.0.0.1:8000/webhooks/elevenlabs/post-call
```

ElevenLabs requires a public HTTPS URL for the hosted service. When `ELEVENLABS_WEBHOOK_SECRET` is set, the backend verifies the ElevenLabs HMAC signature and rejects unsigned or invalid requests. Leave it empty only for local mocked requests.

Ingestion is idempotent on `conversation_id`. The Brain distills a session only when its Process is known and `session_mode != "teaching"`.

### Teacher context

```text
GET /brain/processes/{process_id}/teacher-context
X-Metadosis-Tool-Secret: <shared workspace secret>
```

Set `TEACHER_CONTEXT_SECRET` on the backend and configure the same value as the `X-Metadosis-Tool-Secret` header on the ElevenLabs `load_expert_knowledge` tool. Authentication is enforced when the secret is configured. Never expose it to the browser.

## A local/deployed split to know about

A voice session started from a local frontend still sends its post-call transcript to the webhook configured on the deployed ElevenLabs agent, while local visual observations go to local PostgreSQL. That splits one session across two databases.

For this reason, verify the complete **train → distill → teach** loop against the deployed stack, or tunnel the webhook to your local backend. A default local session cannot prove the full loop end to end.

## Useful commands

```bash
make run-backend          # FastAPI with reload on :8000
make run-frontend         # Next.js development server
make format-fix           # Ruff formatting and import fixes
make lint-fix             # Ruff autofixes
make frontend-typecheck   # Next.js type generation + TypeScript
make frontend-lint        # ESLint
make frontend-build       # Production frontend build
make frontend-check       # Typecheck + lint + build
```

---

**Metadosis does not merely record what happened. It captures why it happened, what could change the decision, and what must never be done—then carries that judgment forward with evidence attached.**
