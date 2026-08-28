from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ModelCategory = Literal["text", "image", "video", "audio"]
ModelTaskType = Literal[
    "chat", "text_to_image", "text_to_video", "image_to_video", "tts"
]
ModelAvailability = Literal["available", "maintenance", "unavailable", "demo"]
CatalogCollection = Literal["featured", "popular", "new"]


class PublicProductModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_model_id: str = Field(pattern=r"^[a-z0-9-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    category: ModelCategory
    task_type: ModelTaskType
    description: str = Field(min_length=1, max_length=1000)
    capabilities: list[str] = Field(max_length=32)
    input_schema: dict[str, object] | None = None
    availability: ModelAvailability
    pricing_summary: str = Field(min_length=1, max_length=240)

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: list[str]) -> list[str]:
        if any(not capability.strip() for capability in value):
            raise ValueError("capabilities must not contain blank values")
        if len(set(value)) != len(value):
            raise ValueError("capabilities must be unique")
        return value


class PublicModelCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: PublicProductModel
    collections: list[CatalogCollection] = Field(max_length=3)

    @field_validator("collections")
    @classmethod
    def validate_collections(
        cls, value: list[CatalogCollection]
    ) -> list[CatalogCollection]:
        if len(set(value)) != len(value):
            raise ValueError("collections must be unique")
        return value


class PublicModelCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PublicModelCatalogItem] = Field(max_length=500)

    @field_validator("items")
    @classmethod
    def validate_model_ids(
        cls, value: list[PublicModelCatalogItem]
    ) -> list[PublicModelCatalogItem]:
        model_ids = [item.model.product_model_id for item in value]
        if len(set(model_ids)) != len(model_ids):
            raise ValueError("product model IDs must be unique")
        return value
