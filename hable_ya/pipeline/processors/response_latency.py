"""Learner response-latency observer (spec #024).

Measures "time to first word": how long the learner takes to start speaking
after the tutor finishes a question or statement — the inverse of the
user-stopped → bot-started number `UserBotLatencyObserver` reports. The two
anchors are `BotStoppedSpeakingFrame` (carries no timestamp, so it is stamped
at observation time — the same posture Pipecat's own latency observer takes on
the bot-started side) and `VADUserStartedSpeakingFrame`, whose `timestamp` is
when the VAD *confirmed* speech; subtracting `start_secs` back-corrects to the
true onset, mirroring the stop-side correction in Pipecat's observer.

The anchor is one-shot and armed only when the learner is not already
speaking, so barge-ins (the bot's stop is *caused* by the learner talking) and
mid-turn pause/resume never measure. A resumed multi-part tutor reply disarms
on `BotStartedSpeakingFrame` and re-arms on its own final stop.

`pending_ms` is a consume-once slot for the `log_turn` handler: each
measurement overwrites it, `pop()` clears it. A turn whose `log_turn` never
fired therefore cannot leak its value onto a later turn — the next onset
overwrites before the next `log_turn` reads.

Always-on (this is a learner metric, not a `latency_debug` diagnostic); the
measurement is logged under `hable_ya.latency` so debug sessions show it
inline with the #013 numbers.
"""

from __future__ import annotations

import logging
import time
from collections import deque

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed

latency_logger = logging.getLogger("hable_ya.latency")

_SEEN_RING_SIZE = 256


class ResponseLatencyObserver(BaseObserver):
    """Records learner speech-onset latency after each completed tutor turn.

    Each measured `(ms)` value is appended to `self.records` (a bounded ring —
    the programmatic view tests assert on) and stored in the consume-once
    `pending_ms` slot for the `log_turn` handler to attach to that turn's
    observation.
    """

    def __init__(self) -> None:
        super().__init__()
        self._seen: deque[int] = deque(maxlen=_SEEN_RING_SIZE)
        self._seen_set: set[int] = set()
        # Wall-clock of the last clean tutor stop, or None when disarmed.
        self._bot_stopped_at: float | None = None
        self._user_speaking = False
        self.pending_ms: int | None = None
        self.records: deque[int] = deque(maxlen=_SEEN_RING_SIZE)

    def pop(self) -> int | None:
        """Return and clear the latest unconsumed measurement."""
        value = self.pending_ms
        self.pending_ms = None
        return value

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        # System frames are pushed through every hop (and both directions);
        # dedup on the frame's process-unique id so each event counts once.
        frame_id = frame.id
        if frame_id in self._seen_set:
            return
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(frame_id)
        self._seen_set.add(frame_id)

        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._user_speaking = True
            if self._bot_stopped_at is not None:
                onset = frame.timestamp - frame.start_secs
                latency_s = onset - self._bot_stopped_at
                self._bot_stopped_at = None
                if latency_s >= 0:
                    ms = int(latency_s * 1000)
                    self.pending_ms = ms
                    self.records.append(ms)
                    latency_logger.info("response_latency_ms=%d", ms)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._user_speaking = False
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_stopped_at = None
        elif isinstance(frame, BotStoppedSpeakingFrame):
            # A stop while the learner is talking is a barge-in, not the end
            # of a tutor prompt — never an anchor.
            if not self._user_speaking:
                self._bot_stopped_at = time.time()
