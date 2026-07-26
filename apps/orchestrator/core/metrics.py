"""In-process metrics counters for /api/metrics/ (v2 observability)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict

_lock = threading.Lock()
_counters: dict[str, int] = defaultdict(int)
_latencies_ms: dict[str, list[float]] = defaultdict(list)
_MAX_SAMPLES = 200


def incr(name: str, amount: int = 1) -> None:
    with _lock:
        _counters[name] += amount


def observe_latency(name: str, ms: float) -> None:
    with _lock:
        samples = _latencies_ms[name]
        samples.append(ms)
        if len(samples) > _MAX_SAMPLES:
            del samples[: len(samples) - _MAX_SAMPLES]


def snapshot() -> dict:
    with _lock:
        latencies = {}
        for key, samples in _latencies_ms.items():
            if not samples:
                continue
            ordered = sorted(samples)
            n = len(ordered)
            p50 = ordered[int(0.50 * (n - 1))]
            p95 = ordered[int(0.95 * (n - 1))]
            latencies[key] = {
                "count": n,
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "last_ms": round(samples[-1], 2),
            }
        return {
            "counters": dict(_counters),
            "latencies": latencies,
            "generated_at": time.time(),
        }


class Timer:
    def __init__(self, name: str):
        self.name = name
        self._start = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        ms = (time.perf_counter() - self._start) * 1000
        observe_latency(self.name, ms)
