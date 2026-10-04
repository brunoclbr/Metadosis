# Welcome to Metadosis

- This repo requires to get access to mic and camera

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
its screen observations go to the local one. Local Postgres therefore never
receives a complete training session, and end-to-end Brain verification (train a
Process, then teach it back) only works against the deployed stack. Use a tunnel
to the local webhook if you need the whole loop locally.
