from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.catalog.repository import _accepted_decision_statement


def test_accepted_decision_query_has_an_explicit_unambiguous_join_root() -> None:
    statement = _accepted_decision_statement(
        product_model_id=uuid4(),
        model_deployment_id=uuid4(),
        effective_at=datetime.now(UTC),
    )

    sql = str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]

    assert "FROM model_revisions JOIN model_deployments" in sql
    assert "JOIN routing_policies" in sql
    assert "JOIN price_bindings" in sql
    assert "JOIN price_versions" in sql
