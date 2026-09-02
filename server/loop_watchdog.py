"""Detects when world work monopolises the event loop that also serves HTTP.

The world runs as an asyncio task on uvicorn's own loop. When a phase does a
long stretch of synchronous work, every HTTP handler and every WebSocket frame
waits behind it, and the dashboard goes stale without anything looking broken —
the front end keeps animating off its last payload. That failure is invisible
from inside the loop, because the loop is precisely what is not running.

So the detector lives in a thread. An asyncio task stamps a heartbeat; the
thread reads the heartbeat's age. Age above the threshold means the loop has not
come back round, and the thread can sample the loop thread's stack to say what
it is stuck in — which the loop itself could never report.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from typing import Optional

import asyncio

from observability import log_event as operational_log

logger = logging.getLogger(__name__)

DEFAULT_POLL_S = 0.05
DEFAULT_STALL_S = 0.5
DEFAULT_PROGRESS_S = 5.0


def _frame_summary(frame, limit: int = 12) -> list[str]:
    """The innermost frames, which is where the blocking call actually is."""
    stack = traceback.extract_stack(frame)
    return [f"{f.filename.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1]}:{f.lineno} {f.name}"
            for f in stack[-limit:]]


class LoopWatchdog:
    """Reports every stretch where the serving loop failed to come back round."""

    def __init__(self, loop: asyncio.AbstractEventLoop, *, run_id: str = "",
                 poll_s: float = DEFAULT_POLL_S, stall_s: float = DEFAULT_STALL_S,
                 progress_s: float = DEFAULT_PROGRESS_S,
                 capture_stacks: bool = True) -> None:
        self.loop = loop
        self.run_id = run_id
        self.poll_s = float(poll_s)
        self.stall_s = float(stall_s)
        # A stall that never ends must still be reported: emit progress at the
        # onset and then at this cadence while the loop stays blocked.
        self.progress_s = float(progress_s)
        self.capture_stacks = bool(capture_stacks)
        self._beat = time.monotonic()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._task: Optional[asyncio.Task] = None
        # Refined by the heartbeat: the loop is not always the main thread
        # (test clients and embedded servers run it elsewhere).
        self._loop_thread_id = threading.main_thread().ident
        # Kept for tests and for /api/run/status, so a stall is reportable and
        # not merely logged into a file nobody reads during a demo.
        self.stalls: list[dict] = []
        self.ongoing: Optional[dict] = None
        self.worst_s = 0.0

    # -- heartbeat (on the loop) ------------------------------------------
    async def _heartbeat(self) -> None:
        self._loop_thread_id = threading.get_ident()
        while not self._stop.is_set():
            self._beat = time.monotonic()
            await asyncio.sleep(self.poll_s)

    # -- detector (off the loop) ------------------------------------------
    def _watch(self) -> None:
        stalling = False
        started = 0.0
        samples: list[list[str]] = []
        last_sample = 0.0
        last_progress = 0.0
        while not self._stop.wait(self.poll_s):
            age = time.monotonic() - self._beat
            if age > self.stall_s:
                now = time.monotonic()
                if not stalling:
                    stalling, started, samples = True, self._beat, []
                    last_sample, last_progress = 0.0, 0.0
                if self.capture_stacks and now - last_sample >= 0.5:
                    last_sample = now
                    frame = sys._current_frames().get(self._loop_thread_id)
                    if frame is not None:
                        samples.append(_frame_summary(frame))
                if last_progress == 0.0 or now - last_progress >= self.progress_s:
                    last_progress = now
                    self._report_ongoing(now - started, samples)
            elif stalling:
                stalling = False
                self._report(time.monotonic() - started, samples)

    def _report_ongoing(self, elapsed_s: float, samples: list[list[str]]) -> None:
        record = {"elapsed_s": round(elapsed_s, 3), "samples": len(samples),
                  "stack": samples[-1] if samples else []}
        self.ongoing = record
        operational_log(
            logger, logging.WARNING, "server.loop.stalling",
            run_id=self.run_id, elapsed_s=record["elapsed_s"],
            samples=record["samples"], stack=record["stack"])

    def _report(self, duration_s: float, samples: list[list[str]]) -> None:
        self.worst_s = max(self.worst_s, duration_s)
        record = {"duration_s": round(duration_s, 3), "samples": len(samples),
                  "stack": samples[len(samples) // 2] if samples else []}
        self.stalls.append(record)
        del self.stalls[:-50]
        self.ongoing = None
        operational_log(
            logger, logging.WARNING, "server.loop.stalled",
            run_id=self.run_id, duration_s=record["duration_s"],
            samples=record["samples"], stack=record["stack"])

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._task = self.loop.create_task(self._heartbeat())
        self._thread = threading.Thread(
            target=self._watch, name="loop-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def status(self) -> dict:
        return {"worst_stall_s": round(self.worst_s, 3),
                "stalls": len(self.stalls),
                "stalling": self.ongoing,
                "recent": self.stalls[-3:]}
