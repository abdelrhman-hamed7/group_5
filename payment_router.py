import os
import re
import time


class DatabaseRepository:
    """Interface for payment transaction records."""

    def get_transaction(self, tx_id: str) -> dict:
        raise NotImplementedError

    def record_transaction(
        self,
        tx_id: str,
        amount: float,
        recipient: str,
        status: str,
        gateway: str,
    ):
        raise NotImplementedError


class PaymentGatewayClient:
    """Interface for third-party payment processors."""

    def process_payment(
        self,
        tx_id: str,
        amount: float,
        recipient: str,
    ) -> bool:
        raise NotImplementedError


class PaymentRouter:
    """Core business engine under verification."""

    def __init__(
        self,
        repo: DatabaseRepository,
        primary_gw: PaymentGatewayClient,
        backup_gw: PaymentGatewayClient,
    ):
        self.repo = repo
        self.primary_gw = primary_gw
        self.backup_gw = backup_gw

        # Read the API key from the environment.
        self.api_key = os.getenv("PAYMENT_GATEWAY_API_KEY")

    def execute_transaction(
        self,
        tx_id: str,
        amount: float,
        recipient: str,
    ) -> str:

        # 1. Security check
        if not self.api_key or self.api_key == "DEBUG_MODE_KEY":
            raise PermissionError(
                "Unauthorized: Production API Key missing "
                "or set to insecure default."
            )

        # 2. Validate the payment amount
        if amount <= 0:
            raise ValueError("Invalid transaction amount")

        # 3. Validate the recipient phone number
        if not re.match(r"^\+[1-9]\d{1,14}$", recipient):
            raise ValueError("Invalid E.164 phone number format")

        # 4. Prevent duplicate successful transactions
        existing = self.repo.get_transaction(tx_id)

        if existing and existing.get("status") == "SUCCESS":
            return "ALREADY_PROCESSED"

        # 5. Try the primary gateway two times
        for attempt in range(2):
            try:
                payment_successful = self.primary_gw.process_payment(
                    tx_id,
                    amount,
                    recipient,
                )

                if payment_successful:
                    self.repo.record_transaction(
                        tx_id,
                        amount,
                        recipient,
                        "SUCCESS",
                        "PRIMARY",
                    )

                    return "COMPLETED_PRIMARY"

            except Exception:
                # Wait briefly before retrying
                time.sleep(0.1)

        # 6. Try the backup gateway
        try:
            payment_successful = self.backup_gw.process_payment(
                tx_id,
                amount,
                recipient,
            )

            if payment_successful:
                self.repo.record_transaction(
                    tx_id,
                    amount,
                    recipient,
                    "SUCCESS",
                    "BACKUP",
                )

                return "COMPLETED_BACKUP"

        except Exception:
            pass

        # 7. Both gateways failed
        self.repo.record_transaction(
            tx_id,
            amount,
            recipient,
            "FAILED",
            "NONE",
        )

        raise RuntimeError(
            "Payment routing failed across all gateways"
        )