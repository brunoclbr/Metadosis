# Handoff: Metadosis Brain + Teacher v0

## Goal
An AI Apprentice that watches an expert work, asks why, distils what it learned into a
structured Work Map with cited evidence, and then teaches that same material to the next
person. Stack: FastAPI/LangGraph backend, Next.js frontend, PostgreSQL, ElevenLabs voice
agent, all on Railway.

## Production
- Frontend: https://metadosis.up.railway.app
- Backend: https://backend-production-8255.up.railway.app
- Railway project `0448f676-3d3a-4db8-9529-5610c6c2e03a`. Backend builds `/Dockerfile`; the
  frontend service root MUST stay `/frontend`.
- ElevenLabs agent `agent_4901m41mp1zge0ha18wcdzp853wn`, post-call webhook
  `90173aed4dd346caba3ad786e92f358c`.
- Brain tool `tool_9201m42dnpcyeqxrt2tr1tx3w576` (`load_expert_knowledge`).
- Latest commit: `eca25b1` (committed locally; **not pushed** — see issue 8).

## What exists

### A. Real webhook ingestion — DONE, verified
Real calls produce `training_sessions` plus `knowledge_documents`, idempotent by
`conversation_id`.

### B. Screen-observation correlation — DONE, verified
`PUT /screen-observations/events` is idempotent and returns 409 if an event is rebound to a
different conversation. The browser buffers events until the authoritative `conversation_id`
arrives from `onConnect`.

### C. Distillation with evidence provenance — DONE, verified with a real call
Every `KnowledgeStep.evidence` entry is a validated reference to a real transcript turn or
screen-observation event. Invalid references fail the session rather than being accepted.
Verified on `conv_2001m42bc4khfd7a66sjnjxpw6bj`: 33 turns, 13 observations, all references
valid.

### D. Teacher v0 — DONE, deployed, works end to end
A **Process** is the durable thing being taught (e.g. "Brainstorming"). One Process
accumulates knowledge across training sessions; learners select a Process, not a past call.

```text
TRAINING                             LEARNING
pick/create Process                  pick Process to learn
   -> expert trains it                  -> same agent, tutor branch
   -> ElevenLabs                        -> load_expert_knowledge(process_id)
   -> post-call webhook                 -> FastAPI -> PostgreSQL
   -> session + knowledge tied          -> tutor teaches from structured JSON
      to process_id
```

**Schema** (migration `003_processes.sql`, additive and idempotent): new `processes` table;
nullable `process_id` on `training_sessions` and `knowledge_documents`. Nullable because
pre-Process sessions keep their evidence and stay readable, they are simply not teachable.

**Endpoints**: `GET/POST /brain/processes`, `GET /brain/processes/{id}`, and
`GET /brain/processes/{id}/teacher-context`. The last one returns the current knowledge plus
the transcript and screen evidence its steps cite, resolved to readable text. 404 = unknown
Process, 409 = exists but nobody has trained it yet. The distinction matters: the tutor must
be able to tell those apart.

**Frontend**: Teach tab has a Process picker (choose or create); Learn tab lists Processes to
learn. The tab that made the selection sets the mode, so the old sidebar mode toggle is gone.

**ElevenLabs**: `load_expert_knowledge` is a webhook tool scoped to `Tutor` and `Tutor Review`
only, with `process_id` bound from the dynamic variable so the model cannot guess it. Tutor
and Tutor Review prompts rewritten to teach from the payload and to say clearly when the
training did not establish something.

**First message**: `first_message` is `{{greeting}}`, a dynamic variable the browser builds per
mode and process name. It is spoken before the router reads `session_mode`, so only the
browser can make it mode-aware; a fixed string also removes the silence the learner used to
hear while the tutor fetched knowledge. Because it always plays, no node greets again.

### E. Camera as a second visual source — DONE, deployed except the git push

Metadosis now learns from what an expert physically does, not only from their screen.

```text
browser screen  --\
                   >-- frame sampling -> FastAPI -> VLM -> {meaningful_change, summary}
browser camera  --/                                   |
                                                      +-> contextual update (both modes)
                                                      +-> persisted evidence (expert only)
```

One pipeline, one endpoint, one model, one event shape, distinguished by
`source: "screen" | "camera"`. What differs is tuning and instructions:

| | screen | camera |
|---|---|---|
| sample interval | 0.5s | 4s |
| compared against | previous sample | last frame actually analysed |
| global / block threshold | 0.006 / 0.06 | 0.035 / 0.20 |
| VLM cooldown | none | 6s |

A screen is still until someone acts; a camera never stops changing. The pixel
test only chooses what is worth looking at, and the camera prompt is the semantic
filter: it names the noise to reject (posture, gesture, autofocus, exposure,
background) and the state changes to report.

**Evidence**: `camera_observation` joins `screen_observation` as a valid evidence
tag. Both remain valid so documents already distilled in production stay
teachable, and the stored row — not the cited tag — decides which the tutor is
told about.

**Mode boundary**: expert observations persist as citable evidence; learner
observations are live context only and never written. `session_mode` gating
distillation remains the structural backstop.

**Prompts** (published, `agtvrsn_6701m42krcpzf8c9s2fc90ck5a5v`): the agent
receives one time-ordered stream tagged `[SCREEN]`/`[CAMERA]` in both modes.
Capture treats an important physical action like an important click and waits
while hands are busy. Tutor compares live observations against loaded expert
knowledge: silent while correct, intervenes before a captured prohibition, hedges
when an observation is ambiguous. Tutor Review may cite a real moment from the
session.

**Expert intro**: the opening line now asks one question — work, years, topic.
It lives in the browser-built greeting so it cannot grow into an interview;
Capture is told it is already done. Nothing about profession or years enters the
Work Map schema; the transcript is enough.

### Physical-task verification script

Train, then teach, both against the deployed stack.

```text
EXPERT  (Teach Metadosis)
  create a Process, e.g. "Changing a bike inner tube"
  Start voice session, answer the one intro question
  Share Screen AND Enable Camera
  show something on screen, then do 3-4 things with your hands
  pause ~3s between physical actions (6s camera cooldown)
  say out loud: 2-3 reasons WHY, one decision rule, one "never do"
  make one step order-dependent: "I always X before Y"
  end the session, wait ~15s for distillation

  verify: GET /brain/processes/{id}/teacher-context
          has steps citing type "camera_observation"

LEARNER (Learn -> same Process)
  Start voice session, Enable Camera
  do the first captured step correctly  -> tutor should stay quiet
  skip X and go straight to Y           -> tutor should intervene
  approach the "never do"               -> tutor should stop you first
```

## Where we are

The full loop works in production. Process "Brainstorming"
(`6fc98f53-bcb5-42da-8a3e-6452e4c3fbc3`) was trained by voice and screen share, and the tutor
teaches its 4-step Work Map back from 6 cited sources. 45 tests passing.

## Open issues

### 1. Teaching sessions contaminated the Work Map — FIXED (`a58ce6a`)
The post-call webhook fires for **every** conversation, so a teaching session was ingested as
expert training and linked to the Process it had just taught. Teacher context serves the most
recently updated document, so the learner's own session replaced the expert's and the tutor's
tool call appeared as step 1 of the process.

Distillation is now gated on `session_mode`. A tutoring session is still recorded against its
Process as a learning record but closes as `skipped`, a terminal status the teacher-context
read never accepts. An absent `session_mode` counts as training, because silently discarding a
real expert demonstration is worse than one stray document.

Three contaminated documents were deleted from production and their sessions set to `skipped`.
Verified afterwards: "Brainstorming" now serves the expert's 4-step Work Map with 6 resolved
evidence sources.

### 2. Teacher-context authentication — DONE
The endpoint requires `X-Metadosis-Tool-Secret`, held as ElevenLabs workspace secret
`ePlXZUeVsAzdd9WWHeio` (`metadosis_teacher_context_secret`) and as `TEACHER_CONTEXT_SECRET` on
the Railway backend. The check is active only when the variable is set, so backend and agent
config can be published in either order. The variable is already set with `--skip-deploys`, so
enforcement begins with the next backend deploy. The screen/camera observation endpoints remain
unauthenticated.

### 3. The tutor can now see the learner — DONE
The `sendContextualUpdate` bridge runs in both modes and carries screen and camera
observations in one tagged, time-ordered stream. Only persistence stays mode-gated.

### 4. Distillation is an in-process background task
A restart loses it, and there is no recovery for sessions stuck in `received`/`processing`.
Allow 10-20s after a call before the Process becomes teachable. A durable queue is deferred.

### 5. Pre-Process documents
The 7 sessions recorded before this deploy have `process_id = NULL` and are not teachable.
Decision: ignore, do not backfill. Inventing provenance for documents that never captured it
would undermine the evidence rule. Teacher-context reports any pre-provenance document as
unteachable rather than repairing it.

### 6. Unresolved
Intermittent ElevenLabs WebRTC audio clipping. Not diagnosable server-side: ElevenLabs
returns no error, no warnings, and no `otlp_traces` for the affected call. Needs browser
`getStats()`, device details, and console output.

### 7. Credentials exposed by earlier Railway CLI output still need rotating.

### 8. `eca25b1` is committed but not pushed
`gh` is authenticated as two accounts and the active one, `mirai-engineering-agent`, has no
write access to `brunoclbr/Metadosis`. Switching accounts is forbidden by the project rules, so
the push needs a human:

```bash
gh auth switch -u brunoclbr && git push origin main
```

Until that lands, production runs the previous frontend and backend: the published agent expects
visual observations and correctly reports having none, and teacher-context is still open because
the new dependency is not deployed.

## Operating notes
- Never read or expose `.env` secrets. Never commit without explicit authorisation.
- After every push to `main`, poll both Railway deployments to terminal status and verify
  backend `/health` plus the frontend URL.
- Focused tests: `PYTHONPATH=. uv run pytest -q tests/test_brain_ingestion.py
  tests/test_backend_lifecycle.py tests/test_teacher_context.py` (35 passing across the suite). Tests are
  gitignored.
- Frontend checks from `frontend/`: `npm run lint && npm run build`.
- ElevenLabs config is the source of truth in `elevenlabs/`. Push with
  `ELEVENLABS_API_KEY= elevenlabs agents push`, then verify with `agents get`.
- Inspect a call: `ELEVENLABS_API_KEY= elevenlabs agents conversations get --conversation-id <id>`.
- Production data: `railway ssh --service Postgres -- psql -U postgres -d railway -c "..."`.
- A locally started session still delivers its post-call transcript to the **deployed**
  backend while its screen observations go to the local one, so the full train-then-teach loop
  can only be verified against the deployed stack.
