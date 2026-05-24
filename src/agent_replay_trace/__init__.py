"""agent-replay-trace - load and step through agent JSONL traces.

You wrote one JSONL event per agent step. Now something's wrong and
you need to figure out which step lit the fuse. `Replay` loads the
trace and lets you iterate, filter, aggregate, or step through it
one event at a time without writing your own loop.

The trace format is intentionally unopinionated: each line is one JSON
object (dict). Common conventions:

  {"kind": "tool_called", "ts": ..., "tool_name": ..., "args": {...}}
  {"kind": "tool_returned", "ts": ..., "tool_name": ..., "result": {...}}
  {"kind": "errored", "ts": ..., "error": "..."}

…but `Replay` does not enforce any field names — it gives you generic
filter/where/by_kind helpers and you decide which keys are meaningful.

    from agent_replay_trace import Replay

    trace = Replay.from_jsonl("runs/agent.jsonl")
    for ev in trace:
        print(ev["kind"], ev.get("tool_name"))

    tool_calls = trace.where(kind="tool_called")
    counts = trace.by_kind()                  # {"tool_called": 5, ...}
    span = trace.duration_s(ts_key="ts")      # max(ts) - min(ts)

    debug = trace.debugger()
    debug.next()
    debug.peek(window=3)
    debug.find(lambda e: e.get("error"))
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

__version__ = "0.1.0"
__all__ = [
    "Replay",
    "Debugger",
]


class Replay:
    """An immutable list of trace events.

    Use `Replay.from_jsonl(path)` to load from disk, or `Replay(events)`
    to wrap an in-memory list.
    """

    def __init__(self, events: Iterable[dict[str, Any]]) -> None:
        self._events: list[dict[str, Any]] = list(events)

    # ---- constructors ------------------------------------------------

    @classmethod
    def from_jsonl(cls, path: str | os.PathLike) -> "Replay":
        p = Path(path)
        out: list[dict[str, Any]] = []
        for n, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"line {n}: failed to parse JSON ({exc.msg})"
                ) from exc
            if not isinstance(obj, dict):
                raise ValueError(f"line {n}: not a JSON object")
            out.append(obj)
        return cls(out)

    # ---- basic access ------------------------------------------------

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            return Replay(self._events[idx])
        return self._events[idx]

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    # ---- filtering ---------------------------------------------------

    def where(
        self,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
        **eq_filters: Any,
    ) -> "Replay":
        """Return a new `Replay` containing only matching events.

        Either pass a callable predicate, or pass keyword equality filters:

            trace.where(kind="tool_called")
            trace.where(lambda e: e.get("error") is not None)
            trace.where(kind="tool_returned", tool_name="search")
        """
        def _match(ev: dict[str, Any]) -> bool:
            if predicate is not None and not predicate(ev):
                return False
            for k, v in eq_filters.items():
                if ev.get(k) != v:
                    return False
            return True

        return Replay(ev for ev in self._events if _match(ev))

    # ---- aggregation -------------------------------------------------

    def by_kind(self, kind_key: str = "kind") -> dict[str, int]:
        """Count events grouped by `kind_key`. Missing values count as None."""
        counts: dict[str, int] = {}
        for ev in self._events:
            k = ev.get(kind_key)
            k_str = str(k) if k is not None else "<no-kind>"
            counts[k_str] = counts.get(k_str, 0) + 1
        return counts

    def duration_s(self, ts_key: str = "ts") -> float | None:
        """`max(ts) - min(ts)` across all events. None if no events have ts."""
        ts: list[float] = []
        for ev in self._events:
            v = ev.get(ts_key)
            if isinstance(v, (int, float)):
                ts.append(float(v))
        if not ts:
            return None
        return max(ts) - min(ts)

    def first(self, **eq_filters: Any) -> dict[str, Any] | None:
        for ev in self._events:
            if all(ev.get(k) == v for k, v in eq_filters.items()):
                return ev
        return None

    def last(self, **eq_filters: Any) -> dict[str, Any] | None:
        for ev in reversed(self._events):
            if all(ev.get(k) == v for k, v in eq_filters.items()):
                return ev
        return None

    def count(self, **eq_filters: Any) -> int:
        return sum(
            1
            for ev in self._events
            if all(ev.get(k) == v for k, v in eq_filters.items())
        )

    # ---- step-through ------------------------------------------------

    def debugger(self) -> "Debugger":
        return Debugger(self._events)


# ---- step-through debugger ------------------------------------------------


@dataclass
class _Position:
    index: int


class Debugger:
    """One-event-at-a-time cursor over a `Replay`."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self._pos = _Position(index=-1)

    @property
    def position(self) -> int:
        """Zero-based index of the *current* event, or -1 before any next()."""
        return self._pos.index

    @property
    def current(self) -> dict[str, Any] | None:
        if 0 <= self._pos.index < len(self._events):
            return self._events[self._pos.index]
        return None

    def next(self) -> dict[str, Any] | None:
        """Advance one step. Returns the new current event, or None at end."""
        if self._pos.index + 1 >= len(self._events):
            self._pos.index = len(self._events)
            return None
        self._pos.index += 1
        return self._events[self._pos.index]

    def prev(self) -> dict[str, Any] | None:
        """Move back one step. Returns the new current event, or None at start."""
        if self._pos.index <= 0:
            self._pos.index = -1
            return None
        self._pos.index -= 1
        return self._events[self._pos.index]

    def reset(self) -> None:
        self._pos.index = -1

    def peek(self, window: int = 1) -> list[dict[str, Any]]:
        """Look at the next `window` events without advancing."""
        if window <= 0:
            return []
        start = max(self._pos.index + 1, 0)
        end = min(start + window, len(self._events))
        return list(self._events[start:end])

    def find(
        self,
        predicate: Callable[[dict[str, Any]], bool],
    ) -> dict[str, Any] | None:
        """Advance forward until `predicate(event)` is True. Return that event."""
        while True:
            ev = self.next()
            if ev is None:
                return None
            if predicate(ev):
                return ev

    def __iter__(self) -> Iterator[dict[str, Any]]:
        while True:
            ev = self.next()
            if ev is None:
                break
            yield ev
