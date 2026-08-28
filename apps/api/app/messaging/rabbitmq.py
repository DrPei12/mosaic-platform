from __future__ import annotations

import json
import re
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Self
from uuid import UUID

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from aio_pika.abc import (
    AbstractChannel,
    AbstractConnection,
    AbstractExchange,
)
from aio_pika.exceptions import AMQPException

from app.core.settings import Settings, settings

CHAT_ROUTING_KEY = "chat.inference.execute"
GENERATION_ROUTING_KEY = "generation.accepted"
VIDEO_GENERATION_ROUTING_KEY = "generation.video.accepted"
_SUPPORTED_ROUTING_KEYS = frozenset(
    {CHAT_ROUTING_KEY, GENERATION_ROUTING_KEY, VIDEO_GENERATION_ROUTING_KEY}
)
_GENERATION_ROUTING_BY_MODALITY: Mapping[str, str] = {
    "text": GENERATION_ROUTING_KEY,
    "image": GENERATION_ROUTING_KEY,
    "audio": GENERATION_ROUTING_KEY,
    "video": VIDEO_GENERATION_ROUTING_KEY,
}
_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9._-]{2,127}$")


class MessagingUnavailable(RuntimeError):
    def __init__(self, code: str = "MESSAGING_UNAVAILABLE") -> None:
        self.code = code
        super().__init__("durable messaging is unavailable")


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: UUID
    tenant_id: UUID
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    aggregate_version: int
    # Routing is transport metadata only. It is intentionally excluded from
    # the identifier-only body so consumers still validate the authoritative
    # outbox row before doing any work.
    routing_key: str | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not _EVENT_TYPE.fullmatch(self.aggregate_type):
            raise ValueError("aggregate_type is invalid")
        if not _EVENT_TYPE.fullmatch(self.event_type):
            raise ValueError("event_type is invalid")
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be positive")
        if self.routing_key is not None and self.routing_key not in _SUPPORTED_ROUTING_KEYS:
            raise ValueError("routing_key is unsupported")

    def body(self) -> bytes:
        return json.dumps(
            {
                "event_id": str(self.event_id),
                "tenant_id": str(self.tenant_id),
                "aggregate_type": self.aggregate_type,
                "aggregate_id": str(self.aggregate_id),
                "event_type": self.event_type,
                "aggregate_version": self.aggregate_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @classmethod
    def from_body(cls, body: bytes) -> EventEnvelope:
        if not body or len(body) > 4096:
            raise ValueError("event envelope body is invalid")
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("event envelope body is invalid") from None
        required = {
            "event_id",
            "tenant_id",
            "aggregate_type",
            "aggregate_id",
            "event_type",
            "aggregate_version",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("event envelope fields are invalid")
        version = value["aggregate_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise TypeError("aggregate_version is invalid")
        try:
            return cls(
                event_id=UUID(str(value["event_id"])),
                tenant_id=UUID(str(value["tenant_id"])),
                aggregate_type=str(value["aggregate_type"]),
                aggregate_id=UUID(str(value["aggregate_id"])),
                event_type=str(value["event_type"]),
                aggregate_version=version,
            )
        except (TypeError, ValueError):
            raise ValueError("event envelope fields are invalid") from None


class RabbitMQPublisher:
    """Robust publisher with confirms and a durable quorum queue."""

    def __init__(self, config: Settings | None = None) -> None:
        self._settings = config or settings
        self._connection: AbstractConnection | None = None
        self._channel: AbstractChannel | None = None
        self._exchange: AbstractExchange | None = None

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def start(self) -> None:
        if self._connection is not None:
            return
        connection: AbstractConnection | None = None
        try:
            connection = await aio_pika.connect_robust(
                self._settings.rabbitmq_url.get_secret_value(),
                timeout=self._settings.rabbitmq_publish_timeout_seconds,
            )
            channel = await connection.channel(
                publisher_confirms=True,
                on_return_raises=True,
            )
            exchange = await channel.declare_exchange(
                self._settings.rabbitmq_exchange,
                ExchangeType.DIRECT,
                durable=True,
            )
            dead_exchange_name = f"{self._settings.rabbitmq_exchange}.dead"
            dead_exchange = await channel.declare_exchange(
                dead_exchange_name,
                ExchangeType.DIRECT,
                durable=True,
            )
            chat_queue = await channel.declare_queue(
                self._settings.rabbitmq_chat_queue,
                durable=True,
                arguments={
                    "x-queue-type": "quorum",
                    "x-dead-letter-exchange": dead_exchange_name,
                    "x-dead-letter-routing-key": f"{CHAT_ROUTING_KEY}.dead",
                },
            )
            await chat_queue.bind(exchange, CHAT_ROUTING_KEY)
            generation_queue = await channel.declare_queue(
                self._settings.rabbitmq_generation_queue,
                durable=True,
                arguments={
                    "x-queue-type": "quorum",
                    "x-dead-letter-exchange": dead_exchange_name,
                    "x-dead-letter-routing-key": f"{GENERATION_ROUTING_KEY}.dead",
                },
            )
            await generation_queue.bind(exchange, GENERATION_ROUTING_KEY)
            video_generation_queue = await channel.declare_queue(
                self._settings.rabbitmq_video_generation_queue,
                durable=True,
                arguments={
                    "x-queue-type": "quorum",
                    "x-dead-letter-exchange": dead_exchange_name,
                    "x-dead-letter-routing-key": f"{VIDEO_GENERATION_ROUTING_KEY}.dead",
                },
            )
            await video_generation_queue.bind(exchange, VIDEO_GENERATION_ROUTING_KEY)
            chat_dead_queue = await channel.declare_queue(
                f"{self._settings.rabbitmq_chat_queue}.dead",
                durable=True,
                arguments={"x-queue-type": "quorum"},
            )
            await chat_dead_queue.bind(dead_exchange, f"{CHAT_ROUTING_KEY}.dead")
            generation_dead_queue = await channel.declare_queue(
                f"{self._settings.rabbitmq_generation_queue}.dead",
                durable=True,
                arguments={"x-queue-type": "quorum"},
            )
            await generation_dead_queue.bind(
                dead_exchange,
                f"{GENERATION_ROUTING_KEY}.dead",
            )
            video_generation_dead_queue = await channel.declare_queue(
                f"{self._settings.rabbitmq_video_generation_queue}.dead",
                durable=True,
                arguments={"x-queue-type": "quorum"},
            )
            await video_generation_dead_queue.bind(
                dead_exchange,
                f"{VIDEO_GENERATION_ROUTING_KEY}.dead",
            )
        except (AMQPException, ConnectionError, OSError, TimeoutError):
            if connection is not None:
                with suppress(AMQPException, ConnectionError, OSError, TimeoutError):
                    await connection.close()
            raise MessagingUnavailable() from None

        self._connection = connection
        self._channel = channel
        self._exchange = exchange

    async def publish(self, envelope: EventEnvelope) -> None:
        if envelope.event_type not in _SUPPORTED_ROUTING_KEYS:
            raise ValueError("unsupported RabbitMQ event type")
        if self._exchange is None:
            raise MessagingUnavailable("MESSAGING_NOT_STARTED")
        routing_key = envelope.routing_key or envelope.event_type
        if routing_key not in _SUPPORTED_ROUTING_KEYS:
            raise ValueError("unsupported RabbitMQ routing key")
        message = Message(
            body=envelope.body(),
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=str(envelope.event_id),
            correlation_id=str(envelope.aggregate_id),
            type=envelope.event_type,
            headers={"aggregate_version": envelope.aggregate_version},
        )
        try:
            await self._exchange.publish(
                message,
                # The explicit route is transport metadata. The body remains
                # an identifier-only envelope so consumers can load the
                # authoritative row by event_id instead of receiving a prompt
                # or request payload.
                routing_key=routing_key,
                mandatory=True,
                timeout=self._settings.rabbitmq_publish_timeout_seconds,
            )
        except (AMQPException, ConnectionError, OSError, TimeoutError):
            raise MessagingUnavailable() from None

    async def close(self) -> None:
        connection = self._connection
        self._exchange = None
        self._channel = None
        self._connection = None
        if connection is not None:
            await connection.close()


def routing_key_for_outbox_event(
    event_type: str,
    payload: Mapping[str, Any],
) -> str:
    """Map the two accepted event families to their explicit broker route."""

    if event_type == CHAT_ROUTING_KEY:
        return CHAT_ROUTING_KEY
    if event_type == GENERATION_ROUTING_KEY:
        modality = payload.get("modality")
        if not isinstance(modality, str):
            raise ValueError("generation outbox modality is required for routing")
        try:
            return _GENERATION_ROUTING_BY_MODALITY[modality]
        except KeyError:
            raise ValueError("generation outbox modality is unsupported") from None
    raise ValueError("unsupported outbox event type")


__all__ = [
    "CHAT_ROUTING_KEY",
    "GENERATION_ROUTING_KEY",
    "VIDEO_GENERATION_ROUTING_KEY",
    "EventEnvelope",
    "MessagingUnavailable",
    "RabbitMQPublisher",
    "routing_key_for_outbox_event",
]
