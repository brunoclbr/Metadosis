# Metadosis Apprentice

This directory is the CLI-managed source of truth for the ElevenLabs agent named **Metadosis Apprentice**.

## Workflow

```text
START
  ↓
Mode Router (silent)
 ├─ session_mode == learning → Capture ↔ Off Record
 │                              ↓
 │                            Debrief → Teach-back ── expert confirms → End
 │                                         └──────── correction loop
 └─ session_mode == teaching → Tutor → Tutor Review → End
```

`session_mode` defaults to `learning` and should be supplied as either `learning` or `teaching` in conversation initiation dynamic variables.

## Dynamic variables

Three variables are supplied by the browser at `startSession` and must stay in sync with `frontend/lib/use-elevenlabs-session.ts`:

| Variable | Purpose |
|----------|---------|
| `session_mode` | `learning` or `teaching`; drives the deterministic router expressions. |
| `process_id` | The Process being trained or learned. Fills the `load_expert_knowledge` path parameter and returns on the post-call webhook so ingestion knows what was trained. Never inferred after the fact. |
| `greeting` | The spoken first message, built per mode and process name in the browser. |

The global first message is `{{greeting}}` rather than a literal string. It is spoken at connect, *before* the router has read `session_mode`, so a hardcoded greeting could not be mode-aware; supplying it as a variable also means the learner hears something immediately instead of waiting on the model or on the knowledge lookup. The silent Mode Router uses `generate_immediately` so it evaluates `session_mode` as soon as that greeting finishes rather than waiting for the user to speak. Because the greeting always plays, **no node may greet again** — Capture and Tutor open straight into their own work.

`Capture → Debrief` uses a deliberately narrow LLM condition: the expert must explicitly indicate that the live task is finished. CLI schema version 1.4.0 does not expose an application-controlled mutable workflow transition signal. Replace this edge with a deterministic signal when that capability is available; do not infer completion from silence or screen activity.

Off Record is a conversational privacy state because no application pause/resume tool exists. It does not claim that screenshot capture, audio, or storage was technically disabled. Teach-back remains active through corrections and exits only after explicit expert confirmation. No Work Map finalization tool is invented; confirmed Teach-back transitions directly to End.

## Managed configuration

- Agent ID: `agent_4901m41mp1zge0ha18wcdzp853wn`
- LLM: `gemini-3.5-flash`, temperature `0.2`
- ASR: Scribe Realtime, high quality
- TTS: Eleven v3 Conversational with Expressive Mode
- Voice ID: `cjVigY5qzO86Huf0OWal` (stable voice from the installed CLI's default template)
- Turn-taking: patient, interruptions enabled
- Maximum conversation duration: 30 minutes
- System tool: `skip_turn`
- Webhook tool: `load_expert_knowledge` (`tool_configs/load_expert_knowledge.json`), scoped to `Tutor` and `Tutor Review` only via `additional_tool_ids`. The learning-branch nodes keep `[]` so they cannot read knowledge back while the expert is still creating it. It GETs `/brain/processes/{process_id}/teacher-context` on the deployed backend, binding `process_id` from the dynamic variable rather than letting the model supply it.

The authenticated account can edit the agent but cannot list the general voice/model catalogs. The voice therefore remains the stable default-template voice; no voice was cloned and no audio is stored here.

## CLI usage

Run commands from this directory. In this repository, set the API-key variable to an empty value so the CLI uses its authenticated macOS Keychain OAuth session instead of loading the parent `.env` file:

```bash
cd elevenlabs
ELEVENLABS_API_KEY= elevenlabs agents status
ELEVENLABS_API_KEY= elevenlabs agents push --dry-run
ELEVENLABS_API_KEY= elevenlabs agents push
ELEVENLABS_API_KEY= elevenlabs agents pull --agent agent_4901m41mp1zge0ha18wcdzp853wn --update --yes
```

CLI 1.4.0 expands pulled configurations with server-default and newer read-only fields that the same CLI cannot push back. The deployed configuration was semantically checked after pull; all prompts, workflow nodes and edges, model, voice, ASR, TTS, dynamic variables, and turn settings were preserved. The checked-in file is restored to the CLI-writable canonical form after that check.

## Manual acceptance

CLI text simulations confirmed that the deployed agent asks for missing reasoning instead of inventing it, refuses to answer a teaching case without case context, and successfully invokes the `skip_turn` system tool. The simulation endpoint did not expose workflow-node execution metadata, so it is not a substitute for the branch-level dashboard checks below.

### Learning / Capture

Start with `session_mode=learning` and verify:

- the greeting plays immediately at connect and names the selected process, and Capture does not greet a second time;
- continuous speech, typing, and rapid navigation do not cause excessive interruption;
- “give me a second” allows the agent to use Skip Turn and remain silent;
- the greeting asks for one short introduction (work, years, topic) and Capture acknowledges it without asking any further background questions;
- questions are grounded in received visual observations, from either `[SCREEN]` or `[CAMERA]`, and ask for non-visible reasoning;
- a camera-only session produces questions about physical actions and never claims to see a screen;
- the agent stays quiet while the expert's hands are visibly busy;
- at least three useful live answers are captured, including one guardrail;
- “off the record” enters Off Record and an explicit resume phrase returns to Capture;
- explicitly saying the live task is finished enters Debrief.

### Debrief and Teach-back

Verify that the agent:

- asks at least three previously unanswered gap-closing questions, one at a time;
- prioritizes exceptions, thresholds, limits, guardrails, and escalation;
- transitions into a separate Teach-back;
- incorporates corrections and repeats the corrected Teach-back;
- does not finish until the expert explicitly confirms material correctness.

### Teaching / Tutor

Start with `session_mode=teaching` and verify that the agent:

- routes silently and directly to Tutor without waiting for the learner to acknowledge the greeting;
- calls `load_expert_knowledge` and responds to its result without requiring another learner turn;
- asks the trainee to reason at important decisions without prompting every step;
- intervenes before a known guardrail is violated;
- explains corrections using only supplied expert logic;
- does not invent absent rules or expert knowledge;
- enters Tutor Review when the case is finished and gives a short evidence-based review.

With the learner's camera on, also verify that the agent:

- stays silent while the learner performs captured steps correctly;
- speaks up when a captured step is skipped or reordered, naming the step rather than reciting the list;
- intervenes before a captured prohibition, not after;
- hedges when an observation is ambiguous (“it looks like…”) instead of asserting it;
- claims no visual knowledge at all before the first observation arrives;
- recalls a real moment from the session in Tutor Review and invents none.
