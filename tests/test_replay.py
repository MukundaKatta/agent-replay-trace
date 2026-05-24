"""Tests for agent_replay_trace."""

from __future__ import annotations

import json

import pytest

from agent_replay_trace import Replay


SAMPLE = [
    {"kind": "tool_called", "ts": 1.0, "tool_name": "search", "args": {"q": "x"}},
    {"kind": "tool_returned", "ts": 1.2, "tool_name": "search", "result": ["a"]},
    {"kind": "tool_called", "ts": 1.5, "tool_name": "fetch", "args": {"u": "/"}},
    {"kind": "errored", "ts": 2.0, "error": "boom"},
    {"kind": "tool_returned", "ts": 2.5, "tool_name": "fetch", "result": None},
]


# ---- constructors -------------------------------------------------------


def test_in_memory_round_trip():
    r = Replay(SAMPLE)
    assert len(r) == 5
    assert r[0]["kind"] == "tool_called"


def test_from_jsonl(tmp_path):
    p = tmp_path / "trace.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in SAMPLE) + "\n", encoding="utf-8")
    r = Replay.from_jsonl(p)
    assert len(r) == 5
    assert r.events[2]["tool_name"] == "fetch"


def test_from_jsonl_skips_blank_lines(tmp_path):
    p = tmp_path / "trace.jsonl"
    payload = "\n".join([
        json.dumps(SAMPLE[0]),
        "",
        json.dumps(SAMPLE[1]),
        "",
    ])
    p.write_text(payload, encoding="utf-8")
    r = Replay.from_jsonl(p)
    assert len(r) == 2


def test_from_jsonl_rejects_invalid_json(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        Replay.from_jsonl(p)
    assert "line 1" in str(exc.value)


def test_from_jsonl_rejects_non_object(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        Replay.from_jsonl(p)
    assert "not a JSON object" in str(exc.value)


# ---- access -------------------------------------------------------------


def test_iter_yields_each_event():
    r = Replay(SAMPLE)
    out = list(r)
    assert out == SAMPLE


def test_indexing():
    r = Replay(SAMPLE)
    assert r[0]["kind"] == "tool_called"
    assert r[-1]["kind"] == "tool_returned"


def test_slice_returns_replay():
    r = Replay(SAMPLE)
    sub = r[:2]
    assert isinstance(sub, Replay)
    assert len(sub) == 2


# ---- where filtering ---------------------------------------------------


def test_where_with_predicate():
    r = Replay(SAMPLE)
    errored = r.where(lambda e: e.get("error") is not None)
    assert len(errored) == 1
    assert errored[0]["kind"] == "errored"


def test_where_with_eq_filter():
    r = Replay(SAMPLE)
    called = r.where(kind="tool_called")
    assert len(called) == 2


def test_where_combines_eq_filters():
    r = Replay(SAMPLE)
    search_calls = r.where(kind="tool_called", tool_name="search")
    assert len(search_calls) == 1
    assert search_calls[0]["args"] == {"q": "x"}


def test_where_returns_new_replay():
    r = Replay(SAMPLE)
    sub = r.where(kind="tool_called")
    assert isinstance(sub, Replay)
    # Original unchanged
    assert len(r) == 5


# ---- aggregation -------------------------------------------------------


def test_by_kind_counts():
    r = Replay(SAMPLE)
    counts = r.by_kind()
    assert counts == {"tool_called": 2, "tool_returned": 2, "errored": 1}


def test_by_kind_custom_key():
    r = Replay([{"category": "a"}, {"category": "b"}, {"category": "a"}])
    counts = r.by_kind(kind_key="category")
    assert counts == {"a": 2, "b": 1}


def test_by_kind_missing_marks_no_kind():
    r = Replay([{}, {"kind": "x"}])
    counts = r.by_kind()
    assert counts == {"<no-kind>": 1, "x": 1}


def test_duration_s():
    r = Replay(SAMPLE)
    assert r.duration_s() == pytest.approx(1.5)


def test_duration_s_none_when_no_ts():
    r = Replay([{"kind": "x"}, {"kind": "y"}])
    assert r.duration_s() is None


def test_first_and_last():
    r = Replay(SAMPLE)
    assert r.first(kind="tool_called")["tool_name"] == "search"
    assert r.last(kind="tool_returned")["tool_name"] == "fetch"


def test_count_with_filter():
    r = Replay(SAMPLE)
    assert r.count(kind="tool_called") == 2
    assert r.count(kind="nope") == 0


# ---- debugger ----------------------------------------------------------


def test_debugger_starts_before_first():
    d = Replay(SAMPLE).debugger()
    assert d.position == -1
    assert d.current is None


def test_debugger_next_advances():
    d = Replay(SAMPLE).debugger()
    ev = d.next()
    assert ev["kind"] == "tool_called"
    assert d.position == 0


def test_debugger_prev_moves_back():
    d = Replay(SAMPLE).debugger()
    d.next(); d.next()
    assert d.position == 1
    d.prev()
    assert d.position == 0


def test_debugger_returns_none_past_end():
    d = Replay(SAMPLE[:2]).debugger()
    d.next(); d.next()
    assert d.next() is None
    assert d.current is None  # past end


def test_debugger_peek_does_not_advance():
    d = Replay(SAMPLE).debugger()
    d.next()
    seen = d.peek(window=2)
    assert len(seen) == 2
    assert d.position == 0  # still at index 0


def test_debugger_find_advances_to_match():
    d = Replay(SAMPLE).debugger()
    err = d.find(lambda e: e.get("kind") == "errored")
    assert err["error"] == "boom"
    assert d.position == 3


def test_debugger_find_returns_none_when_no_match():
    d = Replay(SAMPLE).debugger()
    out = d.find(lambda e: e.get("kind") == "no-such-kind")
    assert out is None


def test_debugger_iter():
    d = Replay(SAMPLE).debugger()
    out = list(d)
    assert len(out) == len(SAMPLE)


def test_debugger_reset():
    d = Replay(SAMPLE).debugger()
    d.next(); d.next()
    d.reset()
    assert d.position == -1
