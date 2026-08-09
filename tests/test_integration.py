import os
import pytest
from payment_router import PaymentRouter, PaymentGatewayClient
from sqlite_repository import SQLiteDatabaseRepository

class DummyGateway(PaymentGatewayClient):
    def __init__(self, succeed=True):
        self.succeed = succeed

    def process_payment(self, tx_id: str, amount: float, recipient: str) -> bool:
        if self.succeed:
            return True
        raise Exception("Gateway failure")

@pytest.fixture(scope='function')
def db_repo():
    db_file = "test_payment_router.db"
    if os.path.exists(db_file):
        os.remove(db_file)
    repo = SQLiteDatabaseRepository(db_path=db_file)
    yield repo
    if os.path.exists(db_file):
        os.remove(db_file)

def test_integration_database_persistence(db_repo, monkeypatch):
    monkeypatch.setenv("PAYMENT_GATEWAY_API_KEY", "PROD_TEST_SECRET_KEY_123")
    primary = DummyGateway(succeed=True)
    backup = DummyGateway(succeed=False)
    router = PaymentRouter(repo=db_repo, primary_gw=primary, backup_gw=backup)

    tx_id = "TXN_INT_001"
    amount = 100.0
    recipient = "+1234567890123"

    result = router.execute_transaction(tx_id, amount, recipient)
    assert result == "COMPLETED_PRIMARY"

    stored = db_repo.get_transaction(tx_id)
    assert stored is not None
    assert stored["status"] == "SUCCESS"
    assert stored["gateway"] == "PRIMARY"

def test_integration_database_idempotency(db_repo, monkeypatch):
    monkeypatch.setenv("PAYMENT_GATEWAY_API_KEY", "PROD_TEST_SECRET_KEY_123")
    primary = DummyGateway(succeed=True)
    backup = DummyGateway(succeed=False)
    router = PaymentRouter(repo=db_repo, primary_gw=primary, backup_gw=backup)

    tx_id = "TXN_INT_002"
    amount = 200.0
    recipient = "+1234567890123"

    result1 = router.execute_transaction(tx_id, amount, recipient)
    assert result1 == "COMPLETED_PRIMARY"

    result2 = router.execute_transaction(tx_id, amount, recipient)
    assert result2 == "ALREADY_PROCESSED"

def test_integration_concurrency_and_mock_lie_proof(db_repo, monkeypatch):
    monkeypatch.setenv("PAYMENT_GATEWAY_API_KEY", "PROD_TEST_SECRET_KEY_123")
    primary = DummyGateway(succeed=True)
    backup = DummyGateway(succeed=False)
    router = PaymentRouter(repo=db_repo, primary_gw=primary, backup_gw=backup)

    tx_id = "TXN_INT_003"
    amount = 300.0
    recipient = "+1234567890123"

    router.execute_transaction(tx_id, amount, recipient)
    
    # Concurrency simulation / duplicate execution attempt
    result = router.execute_transaction(tx_id, amount, recipient)
    assert result == "ALREADY_PROCESSED"

    