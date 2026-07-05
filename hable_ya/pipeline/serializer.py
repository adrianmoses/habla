"""Raw-PCM frame serializer for the /ws/session WebSocket protocol.

Bridges the wire protocol (int16 little-endian mono PCM, binary frames in both
directions, no framing) with Pipecat's frame system. Without this, Pipecat's
FastAPIWebsocketTransport silently drops every inbound message when its
`serializer` param is None (see pipecat/transports/websocket/fastapi.py).
"""

from __future__ import annotations

from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame
from pipecat.serializers.base_serializer import FrameSerializer


class RawPCMSerializer(FrameSerializer):
    def __init__(self, sample_rate: int, num_channels: int = 1) -> None:
        self._sample_rate = sample_rate
        self._num_channels = num_channels

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, bytes):
            return InputAudioRawFrame(
                audio=data,
                sample_rate=self._sample_rate,
                num_channels=self._num_channels,
            )
        return None
