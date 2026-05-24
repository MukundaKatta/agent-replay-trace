# agent-replay-trace

[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/agent-replay-trace.svg)](https://pypi.org/project/agent-replay-trace/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Load JSONL agent traces, filter / aggregate / step through them for debugging.** Zero deps. Format-agnostic.

```python
from agent_replay_trace import Replay

trace = Replay.from_jsonl("runs/agent.jsonl")

# basic iteration
for ev in trace:
    print(ev.get("kind"), ev.get("tool_name"))

# filter (predicate or keyword equality)
errored = trace.where(lambda e: e.get("error") is not None)
search_calls = trace.where(kind="tool_called", tool_name="search")

# aggregate
counts = trace.by_kind()                      # {"tool_called": 5, "errored": 1, ...}
span = trace.duration_s(ts_key="ts")          # max(ts) - min(ts)
first_err = trace.first(kind="errored")
last_call = trace.last(kind="tool_called")

# step through
debug = trace.debugger()
debug.next()                                  # advance one event
debug.peek(window=3)                          # next 3 without advancing
err_ev = debug.find(lambda e: e.get("error")) # jump to first match
debug.prev(); debug.reset()
```

## Why

Every agent stack eventually writes one JSONL event per step (tool called, tool returned, errored, ...). When something goes wrong in prod, you need to read that file. Doing it with `jq` is fine for one-off. Doing it three times a week is when you want a small, opinion-free debugger that knows nothing about your schema but lets you slice it the way you want.

`agent-replay-trace` is one class, one debugger, and a handful of helpers. Format-agnostic — each line is treated as a generic dict.

Pairs with [`agenttrace`](https://github.com/MukundaKatta/agenttrace) (writes the trace) and [`agentsnap`](https://github.com/MukundaKatta/agentsnap) (snapshots the trace for regression tests).

## Install

```bash
pip install agent-replay-trace
```

## API

```python
# load
Replay(events)                           # in-memory list
Replay.from_jsonl(path)                  # one dict per line

# access
for ev in trace: ...
trace[0]; trace[-1]; trace[1:5]          # indexing + slicing (slice returns Replay)
len(trace)
trace.events                             # copy of underlying list

# filter
trace.where(predicate=callable_or_None, **eq_filters) -> Replay

# aggregate
trace.by_kind(kind_key="kind") -> {str: int}
trace.duration_s(ts_key="ts") -> float | None
trace.first(**eq) -> dict | None
trace.last(**eq) -> dict | None
trace.count(**eq) -> int

# step
debug = trace.debugger()
debug.next() / debug.prev() / debug.reset()
debug.peek(window=3) -> list[dict]
debug.find(predicate) -> dict | None
debug.current; debug.position
for ev in debug: ...                     # walks from current position to end
```

## License

MIT
