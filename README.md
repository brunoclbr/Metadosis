# Welcome to Metadosis

- This repo requires to get access to mic and camera

## Visual input

A session can watch two inputs, each enabled by its own button and never opened
until the user presses it:

- **Screen** (`getDisplayMedia`) — sampled every 0.5s with a sensitive pixel
  threshold, because a screen is still until someone acts.
- **Camera** (`getUserMedia`, front camera) — sampled every 4s, compared against
  the last frame actually analysed, with a much larger threshold and a 6s
  cooldown. Camera pixels change constantly, so the coarse test only decides what
  is worth looking at and the vision model decides what is meaningful.

Both flow through the same endpoint, model, and event shape, distinguished by a
`source` of `screen` or `camera`. Raw frames are never stored; only the model's
one-sentence observation is.

In an expert session, confirmed observations are persisted against the
conversation and can be cited as Work Map evidence. In a tutoring session they
are sent to the agent as live context and deliberately never written, so a
learner's actions can never be mistaken for captured expertise.

## Local development

Copy `.env.example` to `.env` and replace the provider placeholders. The PostgreSQL
values already match the local Docker defaults.

Start PostgreSQL 16 with persistent local storage:

```bash
docker compose up -d postgres
```

Start the backend (it applies the idempotent Brain MVP schema at startup):

```bash
make run-backend
```

The ElevenLabs post-call transcription webhook is:

```text
POST http://127.0.0.1:8000/webhooks/elevenlabs/post-call
```

ElevenLabs requires a public HTTPS URL rather than localhost when configuring the
hosted service. Set `ELEVENLABS_WEBHOOK_SECRET` to the signing secret from that
webhook configuration. If the variable is set, unsigned or invalid requests are
rejected; it may be left empty only for local mocked requests.

Because of that, a voice session started against a locally running frontend still
delivers its post-call transcript to the **deployed** backend and database, while
its visual observations go to the local one. Local Postgres therefore never
receives a complete training session, and end-to-end Brain verification (train a
Process, then teach it back) only works against the deployed stack. Use a tunnel
to the local webhook if you need the whole loop locally.

## Teacher context authentication

`GET /brain/processes/{process_id}/teacher-context` serves captured expertise to
the ElevenLabs tutor. Set `TEACHER_CONTEXT_SECRET` to a shared value and
configure the same value as the `X-Metadosis-Tool-Secret` header on the
`load_expert_knowledge` tool, using an ElevenLabs workspace secret rather than a
checked-in value. The check is active only when the variable is set, so the
backend and the agent configuration can be published in either order; an
unconfigured secret is logged on every request. Never expose this value to the
browser.
