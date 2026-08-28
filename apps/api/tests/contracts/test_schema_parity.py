import json
from pathlib import Path

from jsonschema import validate

from app.contracts.errors import ErrorBody, ErrorResponse
from app.contracts.health import HealthResponse

SCHEMAS = Path(__file__).parents[4] / "packages" / "contracts" / "schemas"


def test_python_health_contract_matches_neutral_schema() -> None:
    health = HealthResponse(service="mosaic-api", status="ready", version="0.1.0").model_dump()
    validate(health, json.loads((SCHEMAS / "health.schema.json").read_text(encoding="utf-8")))


def test_python_error_contract_matches_neutral_schema() -> None:
    error = ErrorResponse(
        error=ErrorBody(
            code="DATABASE_NOT_READY",
            message="服务尚未准备好",
            request_id="health-ready",
            retryable=True,
        ),
    ).model_dump()
    validate(error, json.loads((SCHEMAS / "api-error.schema.json").read_text(encoding="utf-8")))
