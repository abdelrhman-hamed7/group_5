import pytest
from unittest.mock import Mock, patch

from payment_router import (
    DatabaseRepository,
    PaymentGatewayClient,
    PaymentRouter,
)


@pytest.fixture
def payment_system(monkeypatch):
    """
    Creates fresh mocked dependencies for every test.
    """

    # Set a secure API key before creating PaymentRouter.
    monkeypatch.setenv(
        "PAYMENT_GATEWAY_API_KEY",
        "PROD_TEST_SECRET_KEY_123",
    )

    repo = Mock(spec=DatabaseRepository)
    primary_gateway = Mock(spec=PaymentGatewayClient)
    backup_gateway = Mock(spec=PaymentGatewayClient)

    # By default, the transaction does not already exist.
    repo.get_transaction.return_value = None

    router = PaymentRouter(
        repo,
        primary_gateway,
        backup_gateway,
    )

    return router, repo, primary_gateway, backup_gateway


# ---------------------------------------------------------
# Interface tests
# ---------------------------------------------------------


def test_database_get_transaction_not_implemented():
    repo = DatabaseRepository()

    with pytest.raises(NotImplementedError):
        repo.get_transaction("TX001")


def test_database_record_transaction_not_implemented():
    repo = DatabaseRepository()

    with pytest.raises(NotImplementedError):
        repo.record_transaction(
            "TX001",
            100.0,
            "+250780000000",
            "SUCCESS",
            "PRIMARY",
        )


def test_gateway_process_payment_not_implemented():
    gateway = PaymentGatewayClient()

    with pytest.raises(NotImplementedError):
        gateway.process_payment(
            "TX001",
            100.0,
            "+250780000000",
        )


# ---------------------------------------------------------
# API key security tests
# ---------------------------------------------------------


def test_missing_api_key_raises_permission_error(monkeypatch):
    monkeypatch.delenv(
        "PAYMENT_GATEWAY_API_KEY",
        raising=False,
    )

    repo = Mock(spec=DatabaseRepository)
    primary_gateway = Mock(spec=PaymentGatewayClient)
    backup_gateway = Mock(spec=PaymentGatewayClient)

    router = PaymentRouter(
        repo,
        primary_gateway,
        backup_gateway,
    )

    with pytest.raises(
        PermissionError,
        match="Unauthorized",
    ):
        router.execute_transaction(
            "TX001",
            100.0,
            "+250780000000",
        )

    primary_gateway.process_payment.assert_not_called()
    backup_gateway.process_payment.assert_not_called()


def test_debug_api_key_raises_permission_error(monkeypatch):
    monkeypatch.setenv(
        "PAYMENT_GATEWAY_API_KEY",
        "DEBUG_MODE_KEY",
    )

    repo = Mock(spec=DatabaseRepository)
    primary_gateway = Mock(spec=PaymentGatewayClient)
    backup_gateway = Mock(spec=PaymentGatewayClient)

    router = PaymentRouter(
        repo,
        primary_gateway,
        backup_gateway,
    )

    with pytest.raises(
        PermissionError,
        match="Unauthorized",
    ):
        router.execute_transaction(
            "TX002",
            100.0,
            "+250780000000",
        )

    primary_gateway.process_payment.assert_not_called()
    backup_gateway.process_payment.assert_not_called()


# ---------------------------------------------------------
# Amount validation tests
# ---------------------------------------------------------


@pytest.mark.parametrize(
    "invalid_amount",
    [0, -1, -50.5],
)
def test_invalid_amount_raises_value_error(
    payment_system,
    invalid_amount,
):
    router, repo, primary_gateway, backup_gateway = payment_system

    with pytest.raises(
        ValueError,
        match="Invalid transaction amount",
    ):
        router.execute_transaction(
            "TX003",
            invalid_amount,
            "+250780000000",
        )

    repo.get_transaction.assert_not_called()
    primary_gateway.process_payment.assert_not_called()
    backup_gateway.process_payment.assert_not_called()


# ---------------------------------------------------------
# Phone number validation tests
# ---------------------------------------------------------


@pytest.mark.parametrize(
    "invalid_phone",
    [
        "0780000000",
        "250780000000",
        "+00012345",
        "+250 780 000 000",
        "invalid-number",
        "",
    ],
)
def test_invalid_phone_raises_value_error(
    payment_system,
    invalid_phone,
):
    router, repo, primary_gateway, backup_gateway = payment_system

    with pytest.raises(
        ValueError,
        match="Invalid E.164 phone number format",
    ):
        router.execute_transaction(
            "TX004",
            100.0,
            invalid_phone,
        )

    repo.get_transaction.assert_not_called()
    primary_gateway.process_payment.assert_not_called()
    backup_gateway.process_payment.assert_not_called()


# ---------------------------------------------------------
# Idempotency test
# ---------------------------------------------------------


def test_successful_existing_transaction_is_not_processed_again(
    payment_system,
):
    router, repo, primary_gateway, backup_gateway = payment_system

    repo.get_transaction.return_value = {
        "tx_id": "TX005",
        "status": "SUCCESS",
    }

    result = router.execute_transaction(
        "TX005",
        100.0,
        "+250780000000",
    )

    assert result == "ALREADY_PROCESSED"

    repo.get_transaction.assert_called_once_with("TX005")
    primary_gateway.process_payment.assert_not_called()
    backup_gateway.process_payment.assert_not_called()
    repo.record_transaction.assert_not_called()


# ---------------------------------------------------------
# Primary gateway success test
# ---------------------------------------------------------


def test_primary_gateway_completes_transaction(
    payment_system,
):
    router, repo, primary_gateway, backup_gateway = payment_system

    primary_gateway.process_payment.return_value = True

    result = router.execute_transaction(
        "TX006",
        250.0,
        "+250780000000",
    )

    assert result == "COMPLETED_PRIMARY"

    primary_gateway.process_payment.assert_called_once_with(
        "TX006",
        250.0,
        "+250780000000",
    )

    repo.record_transaction.assert_called_once_with(
        "TX006",
        250.0,
        "+250780000000",
        "SUCCESS",
        "PRIMARY",
    )

    backup_gateway.process_payment.assert_not_called()


# ---------------------------------------------------------
# Flaky primary gateway retry test
# ---------------------------------------------------------


def test_primary_gateway_retries_after_exception(
    payment_system,
):
    router, repo, primary_gateway, backup_gateway = payment_system

    # First attempt fails; second attempt succeeds.
    primary_gateway.process_payment.side_effect = [
        TimeoutError("Gateway timeout"),
        True,
    ]

    with patch("payment_router.time.sleep") as mock_sleep:
        result = router.execute_transaction(
            "TX007",
            300.0,
            "+250780000000",
        )

    assert result == "COMPLETED_PRIMARY"

    assert primary_gateway.process_payment.call_count == 2

    mock_sleep.assert_called_once_with(0.1)

    repo.record_transaction.assert_called_once_with(
        "TX007",
        300.0,
        "+250780000000",
        "SUCCESS",
        "PRIMARY",
    )

    backup_gateway.process_payment.assert_not_called()


# ---------------------------------------------------------
# Backup gateway test
# ---------------------------------------------------------


def test_backup_gateway_used_when_primary_returns_false(
    payment_system,
):
    router, repo, primary_gateway, backup_gateway = payment_system

    # Both primary attempts return False.
    primary_gateway.process_payment.return_value = False

    # Backup succeeds.
    backup_gateway.process_payment.return_value = True

    result = router.execute_transaction(
        "TX008",
        400.0,
        "+250780000000",
    )

    assert result == "COMPLETED_BACKUP"

    assert primary_gateway.process_payment.call_count == 2

    backup_gateway.process_payment.assert_called_once_with(
        "TX008",
        400.0,
        "+250780000000",
    )

    repo.record_transaction.assert_called_once_with(
        "TX008",
        400.0,
        "+250780000000",
        "SUCCESS",
        "BACKUP",
    )


# ---------------------------------------------------------
# Complete system failure test
# ---------------------------------------------------------


def test_both_gateways_raise_exceptions(
    payment_system,
):
    router, repo, primary_gateway, backup_gateway = payment_system

    primary_gateway.process_payment.side_effect = Exception(
        "HTTP 500 from primary gateway"
    )

    backup_gateway.process_payment.side_effect = Exception(
        "HTTP 500 from backup gateway"
    )

    with patch("payment_router.time.sleep") as mock_sleep:
        with pytest.raises(
            RuntimeError,
            match="Payment routing failed across all gateways",
        ):
            router.execute_transaction(
                "TX009",
                500.0,
                "+250780000000",
            )

    assert primary_gateway.process_payment.call_count == 2
    backup_gateway.process_payment.assert_called_once()

    assert mock_sleep.call_count == 2

    repo.record_transaction.assert_called_once_with(
        "TX009",
        500.0,
        "+250780000000",
        "FAILED",
        "NONE",
    )


def test_both_gateways_return_false(
    payment_system,
):
    router, repo, primary_gateway, backup_gateway = payment_system

    primary_gateway.process_payment.return_value = False
    backup_gateway.process_payment.return_value = False

    with pytest.raises(
        RuntimeError,
        match="Payment routing failed across all gateways",
    ):
        router.execute_transaction(
            "TX010",
            600.0,
            "+250780000000",
        )

    assert primary_gateway.process_payment.call_count == 2
    backup_gateway.process_payment.assert_called_once()

    repo.record_transaction.assert_called_once_with(
        "TX010",
        600.0,
        "+250780000000",
        "FAILED",
        "NONE",
    )