from datetime import timedelta

import pytest

from scripts.operator_accounts import (
    ONE_TIME_CREDENTIAL_TTL,
    PTS_CURRENCY,
    _parser,
    _validate_operator_inputs,
)


def test_operator_account_commands_require_subject_and_reason() -> None:
    with pytest.raises(ValueError):
        _validate_operator_inputs(operator_subject=" ", reason="approved")
    with pytest.raises(ValueError):
        _validate_operator_inputs(operator_subject="ops@example.com", reason=" ")


def test_operator_account_parser_requires_audit_inputs() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            ["create", "--account", "member@example.com", "--tenant-slug", "acme"]
        )
    args = _parser().parse_args(
        [
            "reset",
            "--account",
            "member@example.com",
            "--operator-subject",
            "ops@example.com",
            "--reason",
            "approved reset",
        ]
    )
    assert args.command == "reset"


def test_operator_credentials_are_24_hour_and_wallet_currency_is_points() -> None:
    assert ONE_TIME_CREDENTIAL_TTL == timedelta(hours=24)
    assert PTS_CURRENCY == "PTS"
