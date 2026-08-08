"""External speaking-session handoffs (spec #033).

La Libreta pushes a speaking prompt to Habla server-to-server and gets back a
browser URL. The row that push creates is a *handoff*, not a session: it exists
before microphone consent and before any WebSocket, so a deep link survives a
reload without claiming that paid work has begun.

Three concerns, one per module:

- :mod:`hable_ya.handoff.models` — the durable row as a typed value object.
- :mod:`hable_ya.handoff.prompt` — folding it into the system prompt as
  *quarantined* learner material rather than instructions.
- :mod:`hable_ya.handoff.callback` — the optional outbound completion ping,
  which is the one place Habla fetches a URL an external caller supplied.
"""

from hable_ya.handoff.models import SpeakingHandoff, handoff_from_row
from hable_ya.handoff.prompt import handoff_theme, render_handoff_block

__all__ = [
    "SpeakingHandoff",
    "handoff_from_row",
    "handoff_theme",
    "render_handoff_block",
]
