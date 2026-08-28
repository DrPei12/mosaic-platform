import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
    validate,
)
from pydantic import TypeAdapter, ValidationError
from referencing import Registry, Resource

from app.contracts.auth import AuthSessionResponse, LoginRequest, PasswordChangeRequest
from app.contracts.catalog import (
    PublicModelCatalogItem,
    PublicModelCatalogResponse,
    PublicProductModel,
)
from app.contracts.conversation import (
    ChatStreamEvent,
    ConversationMessage,
    ConversationResponse,
    ConversationSummaryResponse,
    ResumeConversationRequest,
    StreamCompletedEvent,
    StreamDeltaEvent,
    StreamStartedEvent,
)

SCHEMAS = Path(__file__).parents[4] / "packages" / "contracts" / "schemas"


def schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def registry_for(*documents: dict[str, object]) -> Registry[object]:
    registry: Registry[object] = Registry()
    for document in documents:
        registry = registry.with_resource(
            str(document["$id"]), Resource.from_contents(document)
        )
    return registry


def test_catalog_contract_matches_neutral_schema() -> None:
    model = PublicProductModel(
        product_model_id="qwen-3-5-plus",
        display_name="Qwen 3.5 Plus",
        category="text",
        task_type="chat",
        description="用于真实文本对话。",
        capabilities=["多轮对话"],
        availability="available",
        pricing_summary="按实际用量计费",
    )
    response = PublicModelCatalogResponse(
        items=[PublicModelCatalogItem(model=model, collections=["featured"])]
    ).model_dump(mode="json", exclude_none=True)
    public_model_schema = schema("public-product-model.schema.json")
    catalog_schema = schema("model-catalog.schema.json")
    Draft202012Validator(
        catalog_schema,
        registry=registry_for(public_model_schema),
    ).validate(response)


def test_catalog_accepts_wan_text_to_video_model() -> None:
    model = PublicProductModel(
        product_model_id="wan-2-7",
        display_name="Wan 2.7",
        category="video",
        task_type="text_to_video",
        description="用于文字生成视频的模型。",
        capabilities=["文字生成视频"],
        availability="available",
        pricing_summary="按量计费",
    )
    assert model.model_dump(mode="json", exclude_none=True)["task_type"] == "text_to_video"


def test_catalog_rejects_duplicate_collections_and_internal_fields() -> None:
    with pytest.raises(ValidationError):
        PublicModelCatalogItem.model_validate(
            {
                "model": {
                    "product_model_id": "qwen-3-5-plus",
                    "display_name": "Qwen 3.5 Plus",
                    "category": "text",
                    "task_type": "chat",
                    "description": "真实模型",
                    "capabilities": ["chat"],
                    "availability": "available",
                    "pricing_summary": "按量",
                    "provider_model_id": "qwen3.5-plus",
                },
                "collections": ["featured", "featured"],
            }
        )


def test_conversation_and_summary_match_neutral_schemas() -> None:
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    message = ConversationMessage(
        message_id="message-1",
        role="assistant",
        content="你好",
        status="complete",
        created_at=now,
        request_id="request-1",
    )
    conversation = ConversationResponse(
        conversation_id="conversation-1",
        product_model_id="qwen-3-5-plus",
        title="新会话",
        messages=[message],
        updated_at=now,
        active_request_id=None,
    )
    summary = ConversationSummaryResponse(
        conversation_id="conversation-1",
        product_model_id="qwen-3-5-plus",
        title="新会话",
        preview="你好",
        updated_at=now,
    )

    validate(
        conversation.model_dump(mode="json"),
        schema("conversation.schema.json"),
        format_checker=FormatChecker(),
    )
    validate(
        summary.model_dump(mode="json"),
        schema("conversation-summary.schema.json"),
        format_checker=FormatChecker(),
    )


def test_conversation_cursor_and_resume_last_event_id_are_strict() -> None:
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    response = ConversationResponse(
        conversation_id="conversation-1",
        product_model_id="qwen-3-5-plus",
        title="新会话",
        messages=[],
        updated_at=now,
        active_request_id="request-1",
        active_request_cursor=-1,
    )
    assert response.active_request_cursor == -1

    resumed = ResumeConversationRequest.model_validate(
        {"cursor": 4, "Last-Event-ID": 4}
    )
    assert resumed.model_dump() == {"cursor": 4, "last_event_id": 4}

    with pytest.raises(ValidationError):
        ResumeConversationRequest.model_validate(
            {"cursor": 4, "Last-Event-ID": 5}
        )
    with pytest.raises(ValidationError):
        ResumeConversationRequest.model_validate({"cursor": 0, "unexpected": True})
    with pytest.raises(ValidationError):
        ConversationResponse.model_validate(
            {
                **response.model_dump(mode="json"),
                "active_request_cursor": -2,
            }
        )


def test_stream_variants_match_neutral_schema() -> None:
    events: list[ChatStreamEvent] = [
        StreamStartedEvent(
            request_id="request-1",
            conversation_id="conversation-1",
            message_id="message-1",
        ),
        StreamDeltaEvent(
            request_id="request-1",
            conversation_id="conversation-1",
            message_id="message-1",
            sequence=1,
            delta="你",
        ),
        StreamCompletedEvent(
            request_id="request-1",
            conversation_id="conversation-1",
            message_id="message-1",
            sequence=2,
            content="你好",
        ),
    ]
    event_schema = schema("chat-stream-event.schema.json")
    error_schema = schema("api-error.schema.json")
    validator = Draft202012Validator(
        event_schema,
        registry=registry_for(error_schema),
    )
    for event in events:
        validator.validate(
            TypeAdapter(ChatStreamEvent).dump_python(event, mode="json")  # type: ignore[arg-type]
        )


def test_login_and_auth_session_are_strict() -> None:
    LoginRequest(account="owner@example.com", password="correct-horse-battery-staple")
    payload = AuthSessionResponse(
        authenticated=True,
        password_change_required=False,
    ).model_dump(mode="json", by_alias=True)
    assert payload == {"authenticated": True, "passwordChangeRequired": False}

    with pytest.raises(ValidationError):
        LoginRequest.model_validate(
            {"account": "owner@example.com", "password": "short", "tenant": "forged"}
        )


def test_password_change_contract_enforces_the_invited_account_policy() -> None:
    PasswordChangeRequest(
        current_password="temporary-credential",
        new_password="twelve-character",
    )
    for value in ("too-short", "x" * 129):
        with pytest.raises(ValidationError):
            PasswordChangeRequest(
                current_password="temporary-credential",
                new_password=value,
            )
