# Agent Chat frontend

A minimal Next.js and TypeScript interface for the FastAPI/LangGraph backend. It replaces the Streamlit prototype while preserving the same conversation behavior: send a message, reuse one `thread_id`, and create a fresh ID when the user selects **New chat**.

## Run locally

From the repository root:

```bash
make frontend-install
make run-frontend
```

The frontend runs at <http://localhost:3000> and expects FastAPI at `http://127.0.0.1:8000/chat` by default. To use another backend, copy `frontend/.env.example` to `frontend/.env.local` and change `BACKEND_CHAT_URL`.

Do not expose private credentials through variables prefixed with `NEXT_PUBLIC_`; those variables are included in browser bundles.

## Structure and ownership

```text
frontend/
├── app/
│   ├── api/chat/route.ts     # Server-side adapter to FastAPI
│   ├── globals.css           # Responsive visual system
│   ├── layout.tsx            # Document metadata and global layout
│   └── page.tsx              # Page composition
├── components/chat/
│   └── chat-shell.tsx        # Accessible chat interface
└── lib/
    ├── chat-api.ts           # Browser transport and response handling
    ├── chat-contract.ts      # Shared runtime and TypeScript contracts
    └── use-chat.ts           # Conversation interaction state
```

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

For the current local-development flow, `page.tsx` creates an unpredictable UUID-backed thread ID. `use-chat.ts` reuses it for every message until **New chat** creates another ID:

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
