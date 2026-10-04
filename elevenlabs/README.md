# Metadosis Apprentice

This directory is the CLI-managed source of truth for the ElevenLabs agent named **Metadosis Apprentice**.

## Workflow

```text
START
  ↓
Mode Router (silent)
 ├─ session_mode == learning → Capture ↔ Off Record
 │                              ↓
 │                            Debrief → Teach-back ── expert confirms ─┐
 │                                         └──────── correction loop   │
 │                                                                     ↓
 │                                                                 Sign Off → End
 │                                                                     ↑
 └─ session_mode == teaching → Load Expert Knowledge → Tutor → Tutor Review
```

Both branches terminate through `Sign Off`. An `end` node cannot carry a message, so a
farewell has to be its own node; without it the conversation ended in silence the moment
the final edge condition matched.

`session_mode` defaults to `learning` and should be supplied as either `learning` or `teaching` in conversation initiation dynamic variables.

## Dynamic variables

Three variables are supplied by the browser at `startSession` and must stay in sync with `frontend/lib/use-elevenlabs-session.ts`:

| Variable | Purpose |
|----------|---------|
| `session_mode` | `learning` or `teaching`; drives the deterministic router expressions. |
| `process_id` | The Process being trained or learned. Fills the `load_expert_knowledge` path parameter and returns on the post-call webhook so ingestion knows what was trained. Never inferred after the fact. |
| `greeting` | The spoken first message, built per mode and process name in the browser. |

The global first message is `{{greeting}}` rather than a literal string. It is spoken at connect, *before* the router has read `session_mode`, so a hardcoded greeting could not be mode-aware; supplying it as a variable also means the learner hears something immediately instead of waiting on the model or on the knowledge lookup. The silent Mode Router uses `generate_immediately` so it evaluates `session_mode` as soon as that greeting finishes rather than waiting for the user to speak. Because the greeting always plays, **no node may greet again** — Capture and Tutor open straight into their own work.

`session_mode` is derived from the visible workspace tab, never from the last process the
user clicked. Binding it to the click let a process chosen in Teach Metadosis survive a
switch to Learn, so pressing Start opened an expert Capture session for someone waiting to
be tutored. The frontend latches the role at `startSession` and holds it for the duration,
because a tab switch mid-session would otherwise flip whether observations persist as
evidence.

### Entry behaviour is part of the contract

`entry_behavior` decides whether a node speaks on arrival, and it has to agree with how the
greeting ends:

| Branch | Greeting ends with | Entry behaviour |
|--------|--------------------|-----------------|
| `learning` | a question (the expert's introduction) | Capture is `wait_for_user` |
| `teaching` | a statement ("give me one second…") | Tutor is `generate_immediately` |

Capture was `generate_immediately` in production and therefore answered the greeting's own
question before the expert had said anything — the agent said "go ahead and start whenever
you're ready" at 6s, and the expert's introduction only arrived at 24s, by which point
onboarding was already over. Any node reached directly after a greeting that asks something
must wait.

## The question budget

The challenge brief requires at least three grounded live questions with at least one
guardrail, and separately at least three *new* debrief questions. Capture originally had the
floor and no ceiling, which inverted the whole design in production: it asked seven
consecutive questions, the expert's answers decayed to "Fresh, fresh." and "Just keep
going.", and he had to interrupt with "let's just finish the conversation" to escape. Debrief
then fired one second after entry because its condition — already worded as "at least three
distinct previously unanswered debrief questions" — was satisfied by the questions Capture
had asked. Zero debrief questions were asked, so the brief's Module 2 requirement silently
failed.

The fix is a rhythm rather than a hard counter:

- **The unit is one task**, not the session. The expert is asked to work one task at a time,
  which is what gives the agent a natural point to ask at all. The greeting carries that ask,
  but Capture sets the rhythm itself when the greeting did not — the agent and the frontend
  publish separately, so Capture must not assert an opening line an older frontend never sent.
- **Watch → ask → move on.** Capture stays near-silent during a task and asks afterwards.
- **At most three questions per task**, as a ceiling and not a target, spent in priority
  order on the brief's three probes: why this step, what would change the decision, what
  would never be allowed. Leftover curiosity is carried to Debrief instead of spent now.
- **Every second or third task, Capture offers to stop.** Needing to ask the agent to stop is
  treated in the prompt as its failure, not the expert's.
- **Debrief's edge condition now counts only questions asked in Debrief itself**, explicitly
  discounting anything asked during the task, however many there were.

None of this is enforced in code; the counts are internal to the prompt and never spoken.

### Silence has a cost downstream

Restraint and provenance pull against each other, and in production provenance won by
destroying the session. A quiet Capture produced a four-step Work Map in which two steps had
no expert utterance behind them, because nobody had asked. Claim-level v2 provenance requires
expert transcript evidence for any stated reason, so Pydantic rejected the document — all four
steps, the tools and the artifacts — over two uncited `why` fields, and the whole demonstration
was lost.

Ingestion now asks the distiller to repair its own citations once, quoting the validation
error, before stripping whatever still cannot be supported and recording it in the document's
`gaps`. What is *accepted* is unchanged: a stored claim still carries the expert's own words or
it is not stored. The question a quiet session raises is therefore how thin the resulting map
is, not whether it survives — but a Capture that asks nothing still yields nothing worth
teaching, and a Work Map with no step, decision or prohibition is never stored as completed.

### The agent cannot speak on what it sees

`sendContextualUpdate` delivers visual observations without giving the agent the floor, and
that is the platform's design, not a setting. The only turn-triggering primitive is
`sendUserMessage`, which would inject a synthetic `role: user` turn — and the distiller treats
user turns as the expert's own words, so browser-generated text could be cited as expert
evidence. It is therefore never used for this.

The consequence is structural: observations accumulate while the agent is correctly silent,
and only the expert's next turn lets it respond. Capture's `CATCHING UP AFTER SILENCE` rule
exists because of this — when the agent finally gets a turn it must account for the whole
backlog, naming the moment it means. In production it instead spent that turn on a scripted
handoff line, telling the expert to start a task it had just watched them finish. Scripted
opening lines are removed for this reason: a quoted sentence in a prompt gets recited whether
or not it still fits.

`Capture → Debrief` uses a deliberately narrow LLM condition: the expert must explicitly indicate that the live task is finished. CLI schema version 1.4.0 does not expose an application-controlled mutable workflow transition signal. Replace this edge with a deterministic signal when that capability is available; do not infer completion from silence or screen activity.

Off Record is a conversational privacy state because no application pause/resume tool exists. It does not claim that screenshot capture, audio, or storage was technically disabled. Teach-back remains active through corrections and exits only after explicit expert confirmation. No Work Map finalization tool is invented; confirmed Teach-back transitions directly to End.

## Managed configuration

- Agent ID: `agent_4901m41mp1zge0ha18wcdzp853wn`
- LLM: `gemini-3.8-flash`, temperature `0.2`. Upgraded from `gemini-3.5-flash`, which spoke
  a literal `[thought]` tag aloud in production despite an explicit prohibition, and ignored
  both the "do not greet again" rule and the question-restraint rules.
- ASR: Scribe Realtime, high quality
- TTS: Eleven v3 Conversational with Expressive Mode
- Voice ID: `cjVigY5qzO86Huf0OWal` (stable voice from the installed CLI's default template)
- Turn-taking: patient, interruptions enabled
- Maximum conversation duration: 30 minutes
- System tool: `skip_turn`
- Webhook tool: `load_expert_knowledge` (`tool_configs/load_expert_knowledge.json`), executed deterministically by the teaching branch's `Load Expert Knowledge` Dispatch Tool node. Its result edge routes immediately into `Tutor`, which interprets either the returned knowledge or the tool error without waiting for another learner turn. `Tutor Review` retains the tool only as a fallback if context is unavailable. The learning-branch nodes keep `[]` so they cannot read knowledge back while the expert is still creating it. The tool GETs `/brain/processes/{process_id}/teacher-context` on the deployed backend, binding `process_id` from the dynamic variable rather than letting the model supply it.

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
- **exactly one** opening turn is spoken: Capture waits for the expert's introduction and does not answer the greeting's own question;
- the greeting asks the expert to work one task at a time;
- when the expert works *while* answering the introduction, Capture's first turn is about what it saw, and it never invites them to start a task already visibly finished;
- after a long silence the next question names a specific observed moment rather than answering only the last thing said;
- Capture stays quiet *through* a task and asks afterwards, rather than questioning step by step;
- no more than three questions are asked about any single task, and a fourth never follows;
- questions favour why-this-step, what-would-change-the-decision, and what-is-never-allowed over generic ones;
- after the second or third task the agent offers to wrap up, and accepts "yes" immediately;
- the expert never has to interrupt the agent to end the session;
- no `[thought]`, `[plan]` or other bracketed aside is ever spoken;
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

- actually runs: Debrief must not be skipped, and must not transition within a second or two of entry;
- asks at least three previously unanswered gap-closing questions **in this step**, one at a time;
- prioritizes exceptions, thresholds, limits, guardrails, and escalation;
- raises the questions Capture deferred rather than inventing fresh generic ones;
- transitions into a separate Teach-back;
- incorporates corrections and repeats the corrected Teach-back;
- does not finish until the expert explicitly confirms material correctness.

### Sign Off

Both branches must reach it. Verify that:

- the agent speaks a farewell after the expert confirms the Teach-back, and after Tutor Review;
- the session never ends in silence;
- the expert branch names one concrete thing it learned and says it is saved for the next person;
- the tutor branch leaves one thing to practise and does not repeat the whole review;
- no new question is asked in this node.

### Teaching / Tutor

Start with `session_mode=teaching` and verify that the agent:

- routes silently into the `Load Expert Knowledge` tool node without waiting for the learner to acknowledge the greeting;
- follows the visible tool-result edge into Tutor and responds to either knowledge or an error without requiring another learner turn;
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
