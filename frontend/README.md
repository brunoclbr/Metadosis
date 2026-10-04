# Agent Chat frontend

A minimal Next.js and TypeScript interface for the FastAPI/LangGraph backend. It replaces the Streamlit prototype while preserving the same conversation behavior: send a message, reuse one `thread_id`, and create a fresh ID when the user selects **New chat**.

## Run locally

From the repository root:

```bash
make frontend-install
make run-frontend
```

The frontend runs at <http://localhost:3000>. Chat expects FastAPI at `http://127.0.0.1:8000/chat` by default and can be redirected with the server-only `BACKEND_CHAT_URL` variable.

Voice sessions always use the deployed ElevenLabs agent and post-call webhook. To keep Process IDs, visual evidence, and distilled knowledge in one store, local Process and visual-observation routes therefore default to the deployed Brain. Set the server-only `BRAIN_BACKEND_URL` only for isolated backend development with a matching non-production agent and webhook; in production it falls back to `BACKEND_CHAT_URL`.

Do not expose private credentials through variables prefixed with `NEXT_PUBLIC_`; those variables are included in browser bundles.

## Structure and ownership

```text
frontend/
├── app/
│   ├── api/                      # Server-side adapters to FastAPI and ElevenLabs
│   ├── globals.css               # The Metadosis visual system
│   ├── layout.tsx                # Document metadata and global layout
│   └── page.tsx                  # Page composition
├── components/apprentice/
│   ├── metadosis-app.tsx         # Shell; owns session, process, and mode state
│   ├── mode-nav.tsx              # Teach / Learn / Brain
│   ├── session-sidebar.tsx       # Live session status and finish action
│   ├── teach-panel.tsx           # Guided capture sequence
│   ├── learn-panel.tsx           # Process selection and practice setup
│   ├── visual-stage.tsx          # Shared screen/camera view and observations
│   ├── process-picker.tsx        # Process selection and creation
│   ├── source-controls.tsx       # Screen and camera start/stop
│   ├── view-models.ts            # Types shared across the surfaces
│   └── icons.tsx                 # The icon set
└── lib/
    ├── use-elevenlabs-session.ts # Voice session lifecycle
    ├── use-visual-capture.ts     # Frame sampling and change detection
    ├── use-visual-context-bridge.ts # Observations → live agent context
    ├── use-processes.ts          # Brain process list and creation
    ├── use-session-clock.ts      # Elapsed session time
    ├── chat-api.ts               # Browser transport and response handling
    ├── chat-contract.ts          # Shared runtime and TypeScript contracts
    └── use-chat.ts               # Text-chat state (no longer part of the UI)
```

The visual stage is mounted once for the whole workspace and is never unmounted
while a capture runs: two copies would compete for one hook's video ref, and
unmounting mid-session would tear down a live stream.

The text chat surface was removed from the product in favour of the voice
session. `/api/chat`, `chat-api.ts`, `chat-contract.ts`, and `use-chat.ts` are
left intact so the backend contract keeps a working client.

The browser calls the same-origin Next.js `/api/chat` route. That route validates the payload and forwards it to FastAPI using the server-only `BACKEND_CHAT_URL`. Keeping the backend address out of user input avoids browser CORS configuration and prevents the proxy from becoming an arbitrary URL/SSRF mechanism.

```text
Browser chat
    ↓ POST /api/chat
Next.js route handler
    ↓ POST BACKEND_CHAT_URL
FastAPI /chat
    ↓ configurable.thread_id
LangGraph + MongoDBSaver
```

The frontend owns presentation and temporary browser interaction state. Agent messages are rendered as Markdown without enabling raw HTML. FastAPI remains the source of agent behavior, and LangGraph/MongoDB remain the source of checkpoint state.

## Conversation identity

| Identifier | Meaning | Lifetime |
|---|---|---|
| `user_id` | Authenticated application user | User/account |
| `thread_id` | LangGraph conversation and checkpoint lineage | Conversation |
| `request_id` | One HTTP operation, useful for tracing or idempotency | Request |

These identifiers are not interchangeable. One user can own many threads, and one thread can contain many requests.

For the current local-development flow, `page.tsx` creates an unpredictable UUID-backed thread ID. The workspace reuses it to correlate visual observations until **New session** creates another ID:

```json
{
  "message": "Hello",
  "thread_id": "web-..."
}
```

The backend copies the validated value into LangGraph invocation configuration:

```python
config = {
    "configurable": {
        "thread_id": thread_id,
    }
}

result = await workflow.ainvoke(message, config=config)
```

`MongoDBSaver` automatically stores and retrieves checkpoints under that lineage. Reusing the ID continues the conversation; changing it starts separate state. The ID is not a user identity or authorization mechanism.

Messages are intentionally held only in the current page session. MongoDB retains agent checkpoints, but the backend does not yet expose a conversation-history endpoint from which a refreshed browser could rebuild the transcript.

## Production identity

The current client-generated `thread_id` is suitable for local development only. A production backend should:

1. authenticate the request and derive `user_id` server-side;
2. create unpredictable thread IDs;
3. persist the relationship between `user_id` and `thread_id`;
4. authorize thread access before invoking LangGraph; and
5. optionally accept `request_id` for tracing, deduplication, or idempotency.

A production flow normally starts with an authenticated `POST /threads`. The frontend stores the returned ID and sends it to `POST /chat`; the backend verifies ownership before using it as `configurable.thread_id`. Never trust a client-supplied `user_id` as proof of identity.

### Moving to Clerk or another JWT provider

The current UUID identifies a conversation, not a user. To add real accounts:

1. Wrap the Next.js app with the provider's auth context and protect the chat route.
2. Obtain a short-lived JWT after sign-in (with Clerk, `useAuth().getToken()`; use a JWT template if the backend expects one).
3. Send it as `Authorization: Bearer <token>` through the same-origin Next.js proxy to FastAPI. Do not send `user_id` in the request body.
4. In FastAPI, verify the JWT signature against the provider's JWKS, plus its issuer, audience, expiry, and allowed algorithm. Use the verified `sub` claim as the immutable `user_id`.
5. Create threads on the backend, store `{user_id, thread_id}`, and check ownership on every chat/history route before invoking LangGraph.
6. Test missing, expired, and invalid tokens, plus attempts by one user to access another user's thread.

Clerk publishable configuration may be browser-visible, but secret keys and backend JWT-verification settings must remain server-only. Authentication proves who the caller is; authorization still requires the thread ownership check.

## Quality checks

```bash
make frontend-typecheck
make frontend-lint
make frontend-build
```
