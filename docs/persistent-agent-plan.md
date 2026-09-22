# Jarvis as a persistent, event-driven agent

Incremental plan for evolving this repository from a request-driven computer-use agent into a continuously operating personal agent, keeping the working loop intact.

Based on `main` @ `3d338a8`, 2026-09-22. 195 tests passing, Windows + macOS CI.

## Verdict

The repo already has the three things a persistent agent needs most: a resident process, a capability-catalog pattern, and a safety gate. None of them are durable, and none of them are event-driven. The work is to add a store, an event bus, a world model, and a task executor *around* the existing pieces, then re-route the daemon and MCP through them.

Nothing in `typesafe_computer_use/` needs to change in phases 0 through 2. The runner already accepts an injected client, a narration hook, and a gate callable, which is exactly the seam the new layers plug into.

## 1. What exists today, mapped to the target concepts

| Concept | Exists now | Gap |
|---|---|---|
| Observations | Per-step `Screen` + `Item` list in `perception.py`; step files under `runs/`; `on_event` hook in `runner.py` (decision, acted, outcome); voice listener states. | No observation record type. Only GUI observations exist. Nothing is timestamped or queryable outside a run folder. |
| World model | `launcher.open_windows()` recomputed on demand; `_observed_hwnd` global in `windows.py`; `config.APPS` catalog. | No persistent entity state. Nothing survives process exit. |
| Tasks | `RunConfig` + `RunState`; `run.json` with goal, outcome, history; `STOPPED` outcome vocabulary; MCP `active` singleton. | Ephemeral, one at a time, only lives inside `runner.run()`. No priority, deadline, plan, attempts, or resume. |
| Actions / capabilities | `VERBS` dispatch in `actions.py`; `system.COMMANDS`; `config.APPS`; `windows.HOTKEYS`; `launcher.open_app` / `switch_to`. All expressed as `dict[key, description]` for Jev Choice criteria. | No shared `Capability` type, no risk level, no device ownership. The computer-use loop is not itself a capability. |
| Decision layer | `fastpath.decide` (intent), `decide.decide` (per step), `gates.Gate` (Noul). Uniform pattern: state dict + questions dict → `client.system_one`. | No event evaluation. No "is this relevant / anomalous / needs action" question exists yet. |
| Safety | `looks_risky` regex prefilter → Jev Noul → `Confirmer`; foreground `_guard()`; password-field refusal; shell-metachar refusal in `launch_app`; stop file + mouse corner + Ctrl+Shift+Backspace. | Risk levels are implicit. The gate is wired only into the GUI loop via `cfg.gate`; launch, switch, and system commands bypass it. |
| Persistent operation | `daemon.listen` blocks on the mic; one worker thread owning UIA COM; one shared `TypeSafeClient`. | No state on disk except `runs/`. No recovery, no reconcile on start. |
| Events | One `queue.Queue` of utterance strings. | No bus, no sources besides voice, no dedupe, no timers. |
| MCP | `mcp.mjs` spawns `python -m typesafe_computer_use.cli` per run; file-based host handoff (`host/request.json` ↔ `{id}.response.json`); STOP file. | Talks to a throwaway subprocess, not the resident daemon. Two processes can fight over the foreground and the stop file. |
| Devices | `macos.py` shim dispatching to `windows.py` or `macos_native.py`. | Platform adapter exists, but there's no device identity, health, or capability registration. |

## 2. What to reuse as-is

- **The runner's three seams.** `RunConfig.on_event`, `RunConfig.gate`, and the `client=` argument to `run()` were added for Jarvis and are exactly what the executor needs. The loop becomes one capability call with no edits.
- **The "code proposes, Jev chooses" shape.** `fastpath.py` and `gates.py` are the template for the new event evaluator: a state dict, a handful of `Choice`/`Noul` questions, one `system_one` call, confidence gating.
- **Criteria dicts as the capability interface.** `app_criteria()`, `window_criteria()`, `hotkey_criteria()`, and `system.COMMANDS` already are capability catalogs. The registry generates them instead of replacing them.
- **Confirmer.** The pending-question-answered-by-next-utterance mechanism generalizes to task approvals with almost no change.
- **The stop file.** Already checked between phases by `check_abort()`, already written by the hotkey and MCP. It becomes the per-task interrupt.
- **stopkey.py's message-pump thread.** The same pattern (register on own thread, pump `GetMessageW`) is what a `SetWinEventHook` foreground observer needs.
- **Run folders.** Keep them as the raw observation history for GUI tasks. The store indexes them; it doesn't replace them.
- **Lazy platform imports.** Every new module must keep Windows imports inside functions, as `system.py` and `stt.py` do, or the macOS CI job breaks.

## 3. Architectural conflicts to resolve

1. **Everything blocks.** `runner.run`, `Confirmer.confirm` (20 s), `HostWriter.structured` (30 min), and `Listener.run` all block their thread. A persistent agent needs a scheduler that keeps consuming events while a task waits. Fix: the executor owns one "hands" thread that runs blocking work; the event loop is a separate thread; waiting becomes a task *status*, not a blocked call, wherever the wait is longer than a GUI step.
2. **UIA COM thread affinity.** All GUI actuation must stay on the thread that called `UIAutomationInitializerInThread`. Observers that read UIA (window list) must run on that thread or own their own COM init. Fix: observers use Win32/psutil, not UIA, wherever possible; a `reconcile` job that needs UIA is queued onto the hands thread.
3. **Autonomous GUI action collides with the user.** The loop assumes the target window is foreground and nobody else is typing. An unprompted run while the user is working is the single most dangerous behavior in the spec. Fix: a `user.presence` entity from `GetLastInputInfo`, and a policy default that GUI capabilities are *notify-only* while the user is active unless the task was explicitly created for foreground use.
4. **Two processes.** `mcp.mjs` spawns its own Python and holds run state in Node memory. The daemon holds the Jev client and UIA thread. Fix: one resident process; MCP becomes a thin client of it (phase 5).
5. **The gate is a special case.** It's only consulted inside `resolve()`. Fix: a single `policy.authorize(capability, args, context)` that every capability call passes through; the runner's `cfg.gate` is just the GUI-step adapter for it.
6. **Utterances are always new requests.** `Agent.say` classifies every utterance as a fresh intent. In the persistent model an utterance can also answer a pending approval (already handled), query the world ("how's the training?"), or refer to an existing task ("cancel that"). Fix: utterances become `user.utterance` events; fastpath gains `query` and `task_ref` kinds later, not now.
7. **Naming.** The platform shim is imported as `macos` everywhere and `pyproject.toml` still says `typesafe-computer-use` with the KofanLabs homepage. Leave the shim alone; rename the package identity in a housekeeping commit whenever convenient. Not on the critical path.

## 4. Target module layout

New code lands in `jarvis/`. The upstream package stays a library the executor calls.

```text
jarvis/
  store.py          SQLite (stdlib), WAL mode, %LOCALAPPDATA%/jarvis/jarvis.db
  events.py         Event type, bus, dedupe, debounce
  world.py          entity reducer: apply(event) -> changed; snapshot(); reconcile()
  capabilities.py   Capability(id, description, risk, device, fn, args) + registry
  policy.py         READ / LOW / MEDIUM / HIGH; authorize() -> allow | ask | deny
  tasks.py          Task record + status machine, persisted
  executor.py       one hands thread; picks runnable task; runs a capability
  evaluate.py       Jev: relevant? action? notify? over registry candidates
  notify.py         speak (existing Speaker), toast
  observers/
    __init__.py     Observer protocol: start(bus), stop()
    processes.py    psutil diff        -> process.started / process.stopped
    foreground.py   SetWinEventHook     -> window.focused
    presence.py     GetLastInputInfo   -> user.idle / user.active
    timer.py        cron-ish ticks     -> timer.tick
    files.py        watchdog           -> file.changed
    jupyter.py      Jupyter REST       -> jupyter.kernel.busy / idle / died
    gpu.py          nvidia-ml-py       -> gpu.util crossed threshold
    voice.py        wraps Listener     -> user.utterance
  daemon.py         supervisor: store -> observers -> executor -> voice -> API
  api.py            local HTTP on 127.0.0.1, token file; what mcp.mjs and the phone talk to
  agent.py          Agent.say() kept; now creates a task and waits on it
  fastpath.py, gates.py, launcher.py, extract.py, system.py, stopkey.py  (unchanged)
```

### Store schema

```text
events     id, ts, source, kind, key, payload_json, dedupe_key UNIQUE
entities   kind, id, state_json, updated_ts, seen_ts, stale INT
tasks      id, goal, status, priority, deadline, constraints_json, plan_json,
           attempts, capabilities_json, subscriptions_json, last_event_id,
           created_ts, updated_ts
decisions  id, ts, event_id, task_id, question, answer_json, probabilities_json
runs       id, task_id, folder, outcome, started_ts, ended_ts
approvals  id, task_id, question, asked_ts, answered_ts, answer
```

SQLite over anything else: stdlib, single file, survives reboot, trivially inspectable, and one writer thread avoids every locking question. All writes are idempotent on `dedupe_key`, so a duplicate event from a reconnecting observer is a no-op.

### Task status machine

```text
pending --> active --> done
              |  ^      failed
              v  |      cancelled
     waiting_event / waiting_approval / waiting_host
```

Only `active` tasks occupy the hands thread. A waiting task holds no thread and is woken by a matching event, an approval answer, or a host reply. On daemon start every `active` task is demoted to `pending` with `attempts + 1`, because whatever it was doing was interrupted.

## 5. Phases

Each phase ships behind the existing CLI without changing what `jarvis say` or `jarvis listen` do today, until phase 3 swaps the internals.

### Phase 0: groundwork, no behavior change

- `store.py` with the schema above and a `JARVIS_HOME` override for tests.
- `capabilities.py`: `Capability` dataclass and a registry populated from `system.COMMANDS` (LOW), `config.APPS` as `open_app.*` (LOW), `switch_window` (LOW), `notify.speak` (READ), and `computer_use.goal` (LOW, escalates per step). Helper `criteria(filter) -> dict[str, str]` so Jev questions are derived from it.
- `policy.py`: the four levels; `authorize()` returns `allow` for READ and LOW, `ask` for MEDIUM and HIGH, `deny` for anything the registry marks unavailable. Fold `gates.Gate` in: its Noul becomes a runtime escalation that turns a LOW GUI step into HIGH. `Agent` keeps passing a gate to the runner, but it now comes from `policy`.
- Tests: store round-trip and idempotency; registry produces the same criteria dicts `agent.py` produces today; policy table.

**Exit:** 195 tests still pass, `jarvis say` unchanged, a `jarvis.db` appears but nothing reads it yet.

### Phase 1: event bus, world model, cheap Windows observers

- `events.py`: `Event(ts, source, kind, key, payload, dedupe_key)`; bus with subscribe-by-kind, in-process queue, append to store before dispatch.
- `world.py`: pure reducer per event kind; in-memory dict mirrored to `entities`; `snapshot()` returns a compact dict for Jev state and for status output; `reconcile()` lists windows and processes and emits observations so the world is rebuilt from scratch after restart.
- Observers, in this order because each is a few dozen lines and needs no new dependency: `processes` (psutil diff every 2 s), `presence` (idle threshold 120 s), `timer`, `foreground` (SetWinEventHook, own pump thread like `stopkey.py`). Every observer emits on transitions only.
- `daemon.py` becomes a supervisor: open store → start observers → reconcile → start voice as one more observer. The existing `listen` signature stays so the CLI doesn't change.
- New CLI: `jarvis status` prints the world snapshot and recent events from the store, without a running daemon.

**Exit:** kill the daemon, start a process, restart the daemon, and `jarvis status` shows the process because reconcile found it. No Jev calls added yet.

### Phase 2: Jev evaluates events; notify-only actions

- Code filters first: skip events the agent caused itself (its own launches, its own window activations), debounce per key, skip kinds with no subscriber and no standing rule. Only then ask Jev.
- `evaluate.py`: one `system_one` call with `relevant` (Noul), `action` (Choice over registry candidates plus `nothing`), `notify` (Noul). State = the event, the entities it touched, the world snapshot trimmed to that device, and open-task summaries. Every answer is written to `decisions`.
- `notify.py`: `notify.speak` via the existing `Speaker`, `notify.toast` via `winrt` (already a dependency family).
- Budget: a token bucket on Jev calls per minute; overflow events are stored and skipped, never dropped.

**Exit:** with the user idle, a watched process exiting produces a spoken or toast notification, and the decision is visible in the store.

### Phase 3: durable tasks and the executor

- `tasks.py` with the status machine; subscriptions are event patterns that wake a waiting task.
- `executor.py`: the single hands thread (owns UIA COM). Picks the highest-priority `pending` task, runs its next capability through `policy.authorize`, records a `runs` row for GUI capabilities, emits `task.step_done` so the world updates and the evaluator can react.
- `computer_use.goal` wraps `runner.run` with the shared client, `window_title`, and the policy gate; unchanged loop inside.
- `Agent.say` becomes a thin path: utterance → fastpath (unchanged) → either an immediate LOW capability or `tasks.create()` then wait. The CLI and voice UX stay identical.
- Approvals persist: a MEDIUM/HIGH step moves the task to `waiting_approval`, asks by voice or CLI, and resumes on a yes from any channel. The 20 s `Confirmer` timeout stays for mid-GUI-run gates; out-of-run approvals wait indefinitely.

**Exit:** start a goal by voice, kill the daemon mid-run, restart, and the task shows as `pending` with `attempts=2` rather than vanishing.

### Phase 4: the milestone. Jupyter finished, does it matter, tell me

- `observers/jupyter.py`: poll the Jupyter server REST API (`/api/kernels`, `/api/sessions`, token from `jupyter server list`) every 5 s; emit `jupyter.kernel.idle` on busy→idle and `jupyter.kernel.died` on disappearance, keyed by kernel id with the notebook path in the payload. Pair with `process.stopped` for the kernel's pid as a backstop.
- Capability `jupyter.read_outputs` (READ): parse the notebook file's last cells' outputs, returning error text or the tail of stdout.
- Capability `llm.investigate` (READ): the existing Anthropic client, model from `config.answer_model()`, given the outputs and asked for a one-sentence verdict and up to three bounded next actions drawn from the registry. Its proposals go back through Jev and policy; it never executes directly.
- Standing task type `monitor`, created by voice: "monitor this training job and tell me if it fails" → subscriptions on the active kernel. This is also where `fastpath.KINDS` gains `monitor`.

**Exit:** the trace in section 7 runs end to end without a prompt from the user.

### Phase 5: MCP exposes the agent

- `api.py`: local HTTP on `127.0.0.1`, random port written with a bearer token to `%LOCALAPPDATA%/jarvis/api.json`. Endpoints mirror the store: status, world, tasks, events, start_task, stop_task, approve. Chosen over a named pipe because the same API later serves the phone and other device agents over a tunnel.
- `mcp.mjs` becomes a thin client. Keep `typesafe_run`, `typesafe_wait`, `typesafe_respond`, `typesafe_stop`, `typesafe_status`, `typesafe_windows` as compatibility tools mapped to `start_task(kind=computer_use)`; add `jarvis_status`, `jarvis_world`, `jarvis_tasks`, `jarvis_events`, `jarvis_start_task`, `jarvis_stop_task`, `jarvis_approve`.
- The host handoff (`needs_host`) becomes a task in `waiting_host` with the same request/response JSON, so `HostWriter` is unchanged.

**Exit:** Codex or Claude drives a computer-use task through MCP while the voice daemon is running, with no second Python process.

### Phase 6: devices as capability providers (design only)

- `Device` = identity + health + a capability registry + observers. The Windows PC is the in-process device; everything so far is already written against the registry, so nothing changes for it.
- A remote device connects to `api.py`, registers its capabilities and streams its events; the core assigns tasks by required capability. Credentials stay on the device.
- Phone first as a *client* (status, start_task, approve), not a device. Tesla only once its Fleet API capabilities are verified against what the account actually exposes.

## 6. First vertical slice

About a week of evenings, and it proves persistence, recovery, events, and Jev gating at once. Nothing GUI-driving is touched.

1. `store.py` + tests. Round-trip, idempotent insert, WAL.
2. `events.py` + `world.py` with two entity kinds: `process` and `user`. Reducer tests use hand-built events.
3. `observers/processes.py` and `observers/presence.py`. Both are pure Win32/psutil, no UIA.
4. `daemon.py` supervisor with reconcile on start. `jarvis listen` keeps working exactly as now because the voice loop is started last, unchanged.
5. `jarvis status` CLI.
6. `capabilities.py` with `notify.speak` only; `evaluate.py` with candidates `{notify.speak, nothing}`.
7. One standing rule in config: watch process names. Exit of a watched process while idle → Jev → speak.

Then phase 4's Jupyter observer is a fourth observer file and a second capability, not a new architecture.

## 7. Milestone trace

How the target scenario runs once phases 0 through 4 exist.

```text
observers/jupyter    kernel 7a1c busy -> idle           event jupyter.kernel.idle (nb=train.ipynb)
world                jupyter.kernel[7a1c].status=idle    entity updated, seen_ts bumped
tasks                monitor#12 subscribes kernel 7a1c   -> waiting_event -> pending
executor             picks monitor#12                    next step: evaluate
evaluate (Jev)       relevant=0.91  action=jupyter.read_outputs  notify=0.62
policy               READ -> allow
capability           jupyter.read_outputs(train.ipynb)   last cell: Traceback ... CUDA OOM
evaluate (Jev)       anomalous=0.97  action=llm.investigate
capability           llm.investigate                     "Training died at epoch 14, OOM at batch 512.
                                                          Options: rerun at 256 / notify / nothing"
evaluate (Jev)       action=notify.speak (rerun is LOW but user.presence=away, GUI blocked)
policy               READ -> allow
notify.speak + toast "Your training job failed at epoch 14 with a CUDA out-of-memory error."
tasks                monitor#12 -> done; decision rows written; task.step_done emitted
```

## 8. Decisions made here, and open questions

- **SQLite, not a message broker or JSON files.** One file, stdlib, inspectable with any tool, survives reboot. A broker is phase 6's problem when devices are remote.
- **Polling is fine when it's cheap.** A psutil diff costs about 10 ms every 2 s. The spec's rule is "don't screenshot to detect change," and none of the phase 1 observers touch pixels. Push sources (WMI process events, ETW) can replace polling later behind the same observer interface.
- **The LLM is a capability, not a layer.** `llm.investigate` is READ-level and returns proposals. That keeps "code proposes, Jev chooses" true even when the proposer is Claude.
- **Presence gating is the default, not an option.** Autonomous GUI action while the user is at the keyboard is the failure mode most likely to make them turn the whole thing off. Notify-only while active, act while idle, and explicit tasks can override.
- **Local HTTP for the control plane.** Serves MCP now and the phone later with one surface. Bound to loopback with a token file until a device story exists.

**Open questions.** Which Jupyter setup is in use: classic server, JupyterLab, or VS Code's kernel? The REST observer assumes a Jupyter server with a token; VS Code-hosted kernels need a different source. And should watched processes and notebook paths live in `config.py` beside `APPS`, or in a user file under `%LOCALAPPDATA%/jarvis`? The user file keeps the repo generic.
