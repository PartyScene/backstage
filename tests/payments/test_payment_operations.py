import pytest
from faker import Faker
from quart.datastructures import FileStorage
from tests.payments.test_payments_base import TestPaymentsBase
import io
from http import HTTPStatus

fake = Faker()


@pytest.mark.asyncio(loop_scope="session")
class TestPaymentOperations(TestPaymentsBase):
    async def test_create_payment_intent(self, payments_client, mock_event, bearer):
        """Test creating a new payment intent."""
        response = await self.create_payment_intent(payments_client, mock_event['id'], 3, bearer)
        print(response)
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "data" in response_json
        payment_response_data = response_json["data"]
        assert "client_secret" in payment_response_data
        assert payment_response_data["event_id"] == mock_event["id"]
        assert payment_response_data["amount"] > 0  # Assuming amount is greater than zero for valid paymentss
        assert "pub_key" in payment_response_data