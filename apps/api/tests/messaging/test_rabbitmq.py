import json
from uuid import uuid4

import pytest

import app.messaging.rabbitmq as rabbitmq_module
from app.core.settings import Settings
from app.messaging.rabbitmq import (
    CHAT_ROUTING_KEY,
    GENERATION_ROUTING_KEY,
    VIDEO_GENERATION_ROUTING_KEY,
    EventEnvelope,
    MessagingUnavailable,
    RabbitMQPublisher,
    routing_key_for_outbox_event,
)


def test_event_envelope_is_minimal_and_contains_no_prompt() -> None:
    envelope = EventEnvelope(
        event_id=uuid4(),
        tenant_id=uuid4(),
        aggregate_type="inference_request",
        aggregate_id=uuid4(),
        event_type=CHAT_ROUTING_KEY,
        aggregate_version=1,
    )

    payload = json.loads(envelope.body())
    assert set(payload) == {
        "event_id",
        "tenant_id",
        "aggregate_type",
        "aggregate_id",
        "event_type",
        "aggregate_version",
    }
    assert "prompt" not in payload
    assert "messages" not in payload


def test_event_envelope_round_trips_and_rejects_payload_smuggling() -> None:
    envelope = EventEnvelope(
        event_id=uuid4(),
        tenant_id=uuid4(),
        aggregate_type="inference_request",
        aggregate_id=uuid4(),
        event_type=CHAT_ROUTING_KEY,
        aggregate_version=1,
    )
    assert EventEnvelope.from_body(envelope.body()) == envelope

    payload = json.loads(envelope.body())
    payload["prompt"] = "must not cross the broker"
    with pytest.raises(ValueError):
        EventEnvelope.from_body(json.dumps(payload).encode())


@pytest.mark.asyncio
async def test_publisher_fails_closed_before_confirm_channel_is_started() -> None:
    publisher = RabbitMQPublisher()
    envelope = EventEnvelope(
        event_id=uuid4(),
        tenant_id=uuid4(),
        aggregate_type="inference_request",
        aggregate_id=uuid4(),
        event_type=CHAT_ROUTING_KEY,
        aggregate_version=1,
    )

    with pytest.raises(MessagingUnavailable) as error:
        await publisher.publish(envelope)
    assert error.value.code == "MESSAGING_NOT_STARTED"


def test_envelope_rejects_unknown_or_nonpositive_values() -> None:
    with pytest.raises(ValueError):
        EventEnvelope(
            event_id=uuid4(),
            tenant_id=uuid4(),
            aggregate_type="inference_request",
            aggregate_id=uuid4(),
            event_type="INVALID EVENT",
            aggregate_version=0,
        )


def test_generation_routing_keeps_video_out_of_image_audio_queue() -> None:
    assert routing_key_for_outbox_event(
        GENERATION_ROUTING_KEY,
        {"modality": "image"},
    ) == GENERATION_ROUTING_KEY
    assert routing_key_for_outbox_event(
        GENERATION_ROUTING_KEY,
        {"modality": "audio"},
    ) == GENERATION_ROUTING_KEY
    assert routing_key_for_outbox_event(
        GENERATION_ROUTING_KEY,
        {"modality": "video"},
    ) == VIDEO_GENERATION_ROUTING_KEY


class _Exchange:
    def __init__(self, name: str) -> None:
        self.name = name
        self.published: list[tuple[object, str, bool]] = []

    async def publish(
        self,
        message: object,
        routing_key: str,
        *,
        mandatory: bool,
        timeout: float,
    ) -> None:
        assert timeout == 10.0
        self.published.append((message, routing_key, mandatory))


class _Queue:
    def __init__(self, name: str, arguments: dict[str, str]) -> None:
        self.name = name
        self.arguments = arguments
        self.bindings: list[tuple[str, str]] = []

    async def bind(self, exchange: _Exchange, routing_key: str) -> None:
        self.bindings.append((exchange.name, routing_key))


class _Channel:
    def __init__(self) -> None:
        self.exchanges: dict[str, _Exchange] = {}
        self.queues: dict[str, _Queue] = {}

    async def declare_exchange(
        self,
        name: str,
        _kind: object,
        *,
        durable: bool,
    ) -> _Exchange:
        assert durable is True
        exchange = _Exchange(name)
        self.exchanges[name] = exchange
        return exchange

    async def declare_queue(
        self,
        name: str,
        *,
        durable: bool,
        arguments: dict[str, str],
    ) -> _Queue:
        assert durable is True
        queue = _Queue(name, arguments)
        self.queues[name] = queue
        return queue


class _Connection:
    def __init__(self) -> None:
        self.channel_options: dict[str, bool] | None = None
        self.channel_instance = _Channel()
        self.closed = False

    async def channel(self, **kwargs: bool) -> _Channel:
        self.channel_options = kwargs
        return self.channel_instance

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_publisher_declares_quorum_topology_and_uses_confirms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()

    async def connect(*_: object, **__: object) -> _Connection:
        return connection

    monkeypatch.setattr(rabbitmq_module.aio_pika, "connect_robust", connect)
    publisher = RabbitMQPublisher(Settings(_env_file=None))
    envelope = EventEnvelope(
        event_id=uuid4(),
        tenant_id=uuid4(),
        aggregate_type="inference_request",
        aggregate_id=uuid4(),
        event_type=CHAT_ROUTING_KEY,
        aggregate_version=1,
    )

    await publisher.start()
    await publisher.publish(envelope)
    await publisher.close()

    assert connection.channel_options == {
        "publisher_confirms": True,
        "on_return_raises": True,
    }
    queue = connection.channel_instance.queues["mosaic.chat.inference"]
    assert queue.arguments["x-queue-type"] == "quorum"
    assert queue.bindings == [("mosaic.events", CHAT_ROUTING_KEY)]
    generation_queue = connection.channel_instance.queues["mosaic.generation.execute"]
    assert generation_queue.arguments["x-queue-type"] == "quorum"
    assert generation_queue.bindings == [("mosaic.events", GENERATION_ROUTING_KEY)]
    video_queue = connection.channel_instance.queues["mosaic.generation.video.execute"]
    assert video_queue.arguments["x-queue-type"] == "quorum"
    assert video_queue.arguments["x-dead-letter-routing-key"] == (
        f"{VIDEO_GENERATION_ROUTING_KEY}.dead"
    )
    assert video_queue.bindings == [("mosaic.events", VIDEO_GENERATION_ROUTING_KEY)]
    assert connection.channel_instance.queues["mosaic.generation.execute.dead"].bindings == [
        ("mosaic.events.dead", f"{GENERATION_ROUTING_KEY}.dead")
    ]
    assert connection.channel_instance.queues[
        "mosaic.generation.video.execute.dead"
    ].bindings == [("mosaic.events.dead", f"{VIDEO_GENERATION_ROUTING_KEY}.dead")]
    exchange = connection.channel_instance.exchanges["mosaic.events"]
    assert len(exchange.published) == 1
    message, routing_key, mandatory = exchange.published[0]
    assert routing_key == CHAT_ROUTING_KEY
    assert mandatory is True
    assert isinstance(message, rabbitmq_module.Message)
    assert message.delivery_mode == rabbitmq_module.DeliveryMode.PERSISTENT
    assert connection.closed is True


@pytest.mark.asyncio
async def test_publisher_uses_event_type_as_routing_key_without_payload_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()

    async def connect(*_: object, **__: object) -> _Connection:
        return connection

    monkeypatch.setattr(rabbitmq_module.aio_pika, "connect_robust", connect)
    publisher = RabbitMQPublisher(Settings(_env_file=None))
    envelope = EventEnvelope(
        event_id=uuid4(),
        tenant_id=uuid4(),
        aggregate_type="generation_job",
        aggregate_id=uuid4(),
        event_type=GENERATION_ROUTING_KEY,
        aggregate_version=1,
    )

    await publisher.start()
    await publisher.publish(envelope)

    message, routing_key, _ = connection.channel_instance.exchanges["mosaic.events"].published[0]
    assert routing_key == GENERATION_ROUTING_KEY
    assert isinstance(message, rabbitmq_module.Message)
    assert b"prompt" not in message.body
