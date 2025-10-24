from datetime import datetime
import os
import stripe
import orjson as json

from typing import Dict, Any, Optional
from http import HTTPStatus

from quart import (
    current_app as app,
    request,
    jsonify,
)
from payments.src.connectors import PaymentsDB
from shared.classful import route, QuartClassful
from shared.utils import get_client_ip

from quart_jwt_extended import jwt_required, get_jwt_identity
from aiocache import cached

import stripe

STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PUB_KEY = os.environ.get("STRIPE_PUB_KEY", "")
STRIPE_PRIV_KEY = os.environ.get("STRIPE_PRIV_KEY", "")
PAYMENT_WEBHOOK_URL = os.environ.get("PAYMENT_WEBHOOK_URL", "")
HOST_KYC_PRICE = os.environ.get("HOST_KYC_PRICE", 10.00)

stripe.api_key = STRIPE_PRIV_KEY

if not STRIPE_WEBHOOK_SECRET or not STRIPE_PUB_KEY or not STRIPE_PRIV_KEY:
    raise ValueError(
        "Stripe webhook secret and API keys must be set in environment variables."
    )


class BaseView(QuartClassful):

    def __init__(self):
        self.conn: PaymentsDB = app.conn
        self.redis = app.redis
        self.stripe_client: Optional[StripeClient] = stripe.StripeClient(STRIPE_PRIV_KEY)
        self.check_and_assign_webhook()

    def check_and_assign_webhook(self):
        if self.stripe_client:
            webhook_endpoints = self.stripe_client.webhook_endpoints.list(
                params={"limit": 100}
            )
            if any(
                endpoint.url == PAYMENT_WEBHOOK_URL for endpoint in webhook_endpoints
            ):
                app.logger.debug("Webhook endpoint already exists.")
            else:
                app.logger.debug(
                    "Creating new webhook endpoint with URL %s" % PAYMENT_WEBHOOK_URL
                )
                self.stripe_client.webhook_endpoints.create(
                    params={
                        "url": PAYMENT_WEBHOOK_URL,
                        "enabled_events": [
                            "payment_intent.succeeded",
                            "payment_intent.payment_failed",
                        ],
                        "description": "Webhook for payment intents",
                    }
                )
                app.logger.info("Webhook endpoint created successfully.")
            return webhook_endpoints

    @route("/", methods=["GET"])
    async def index(self):
        return await self.healthcheck()

    @route("/payments/health", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def healthcheck(self):
        """
        Simple health check endpoint that verifies service and dependency status.
        Returns 200 OK if everything is healthy, 503 Service Unavailable otherwise.
        """
        health_status = {
            "service": "microservices.payments",
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "dependencies": {"database": "unknown", "redis": "unknown"},
        }
        message = "Service is healthy"
        status_code = HTTPStatus.OK

        # Check database connection
        try:
            db_info = await self.conn._info()
            health_status["dependencies"]["database"] = "healthy"
        except Exception as e:
            app.logger.error(f"Database health check failed: {e}")
            health_status["dependencies"]["database"] = "unhealthy"
            health_status["status"] = "degraded"
            message = "Service degraded: Database connection failed"
            status_code = HTTPStatus.SERVICE_UNAVAILABLE

        # Check Redis connection
        try:
            redis_ping = await self.redis.ping()
            health_status["dependencies"]["redis"] = (
                "healthy" if redis_ping else "unhealthy"
            )
            if not redis_ping:
                health_status["status"] = "degraded"
                message = "Service degraded: Redis connection failed"
                status_code = HTTPStatus.SERVICE_UNAVAILABLE
        except Exception as e:
            app.logger.error(f"Redis health check failed: {e}")
            health_status["dependencies"]["redis"] = "unhealthy"
            health_status["status"] = "degraded"
            message = "Service degraded: Redis connection failed"
            status_code = HTTPStatus.SERVICE_UNAVAILABLE

        return (
            jsonify(data=health_status, message=message, status=status_code.phrase),
            status_code,
        )

    async def create_payment_stripe_intent(
        self, amount: int, user_id, event_id, ticket_count: int = 1, ip_address: str = "127.0.0.1", host_stripe_account_id: str = None, coupon_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a Stripe payment intent for the given amount and user ID."""
        if not self.stripe_client:
            raise ValueError("Stripe client is not initialized.")
        total_amount = self.calculate_total_amount(float(amount))
        app.logger.debug(
            f"Creating payment intent for user {user_id} with amount {total_amount} for event {event_id} and ticket count {ticket_count}"
        )

        if coupon_code:
            COUPON = await stripe.Coupon.retrieve_async(coupon_code)
            total_amount = total_amount * (COUPON.percent_off / 100)

        tax_calculation_params = {
            "currency": "usd",
            "line_items": [
                {
                    "amount": int(total_amount * 100),
                    "quantity": ticket_count,
                    "reference": event_id
                }
            ],
            "customer_details": {"ip_address": ip_address}
        }

        CALCULATION = await stripe.tax.Calculation.create_async(**tax_calculation_params) # Calculate tax

        # Build payment intent parameters
        payment_params = {
            "amount": CALCULATION.amount_total,  # Total includes tax
            "currency": "usd",
            "metadata": {
                "user_id": user_id,
                "ticket_count": str(ticket_count),
                "event_id": event_id,
                "tax_calculation_id": CALCULATION.id,  # Store for reference
            },
            "automatic_payment_methods": {
                "enabled": True,
            },
        }
        
        # Add destination charge if host has Stripe Connect account
        if host_stripe_account_id:
            payment_params["transfer_data"] = {
                "destination": host_stripe_account_id,
            }
            payment_params["application_fee_amount"] = int(0.03 * CALCULATION.amount_total)  # 3% platform fee
            app.logger.info(f"Creating destination charge to {host_stripe_account_id} with 3% platform fee")
        else:
            app.logger.warning(f"Event {event_id} host has no Stripe account - processing as direct charge")
        
        # Create a Stripe payment intent
        payment_intent = await self.stripe_client.payment_intents.create_async(payment_params)
        return payment_intent

    def calculate_total_amount(self, base_amount: float) -> float:
        """
        Calculate the total amount including Stripe fees.
        The formula is: (base_amount + 0.30) / (1 - 0.029)
        where 0.30 is the fixed fee and 0.029 is the percentage fee.
        """
        stripe_percentage = 0.029
        stripe_fixed = 0.30
        total_amount = (base_amount + stripe_fixed) / (1 - stripe_percentage)
        return total_amount

    async def create_kyc_stripe_intent(self, user_id, coupon_code = None) -> Dict[str, Any]:
        """Create a Stripe payment intent for the given amount and user ID."""
        if not self.stripe_client:
            raise ValueError("Stripe client is not initialized.")

        total_amount = self.calculate_total_amount(HOST_KYC_PRICE)

        if coupon_code:
            COUPON = await stripe.Coupon.retrieve_async(coupon_code)
            discount_multiplier = 1 - (COUPON.percent_off / 100)
            total_amount = total_amount * discount_multiplier
            app.logger.warning(f"Applying coupon {coupon_code} ({COUPON.percent_off}% off) to kyc payment - new amount: {total_amount}")

        payment_intent = await self.stripe_client.payment_intents.create_async(
            {
                "amount": int(total_amount * 100),  # Convert to cents
                "currency": "usd",
                "metadata": {"user_id": user_id, "type": "KYC_PAYMENT"},
            }
        )
        return payment_intent

    @route("/payments/<event_id>/create-intent", methods=["POST"])
    @jwt_required
    async def create_intent(self, event_id: str):
        """Create payment intent for a user & event"""
        try:
            user_id = get_jwt_identity()
            data: dict = await request.get_json()
            ticket_count = data.get("ticket_count", 1)

            # Validate ticket count
            if not isinstance(ticket_count, int) or ticket_count < 1:
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="Ticket count must be a positive integer",
                        status=status_code.phrase
                    ),
                    status_code,
                )
            
            # Apply business limit (max 100 tickets per transaction)
            if ticket_count > 100:
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="Maximum 100 tickets per transaction",
                        status=status_code.phrase
                    ),
                    status_code,
                )

            # Verify the event exists
            event = await self.conn._fetch(event_id)
            if not event:
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(message="Event not found", status=status_code.phrase),
                    status_code,
                )

            coupon_code = data.get("coupon_code", "")



            # Get host's Stripe Connect account ID if available
            host_data = event.get("host", {})
            host_stripe_account_id = host_data.get("stripe_account_id", "")
            
            # Validate host has completed Stripe onboarding for paid events
            if event.get("price", 0) > 0 and not host_stripe_account_id:
                app.logger.warning(
                    f"Event {event_id} is paid but host {host_data.get('id')} has no Stripe account"
                )
                # Optionally enforce this as required:
                # status_code = HTTPStatus.BAD_REQUEST
                # return (
                #     jsonify(
                #         message="Event host must complete Stripe onboarding to sell tickets",
                #         status=status_code.phrase
                #     ),
                #     status_code,
                # )
            
            # Create a stripe payment intent
            intent = await self.create_payment_stripe_intent(
                amount=event.get("price", 0),
                user_id=user_id,
                event_id=event_id,
                ticket_count=ticket_count,
                ip_address=get_client_ip(request),
                host_stripe_account_id=host_stripe_account_id if host_stripe_account_id else None,
                coupon_code=coupon_code
            )

            # return the intent client secret
            return (
                jsonify(
                    data={
                        "client_secret": intent["client_secret"],
                        "pub_key": STRIPE_PUB_KEY,
                        "amount": intent["amount"],
                        "currency": intent["currency"],
                        "event_id": event_id,
                    },
                    message="Payment intent created successfully.",
                    status=HTTPStatus.OK.phrase,
                ),
                HTTPStatus.OK,
            )
        except Exception as e:
            app.logger.error(
                f"Error creating payment intent for event {event_id}: {str(e)}",
                exc_info=True,
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to create payment intent: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/payments/kyc/create-intent", methods=["POST"])
    @jwt_required
    async def create_kyc_intent(self):
        """Create KYC payment intent"""
        try:
            user_id = get_jwt_identity()

            coupon_code = ""

            # Apply early adopter coupon
            events_count = await self.conn._get_events_count()
            if events_count and events_count < 110: # Apply coupon for first 110 events
                coupon_code = "EARLY_ADOPTER"
                app.logger.warning(f"Applying EARLY_ADOPTER coupon for user {user_id}")


            # Create a stripe payment intent
            intent = await self.create_kyc_stripe_intent(
                user_id=user_id,
                coupon_code=coupon_code
            )

            # return the intent client secret
            return (
                jsonify(
                    data={
                        "client_secret": intent["client_secret"],
                        "pub_key": STRIPE_PUB_KEY,
                        "amount": intent["amount"],
                        "currency": intent["currency"],
                    },
                    message="Payment intent created successfully.",
                    status=HTTPStatus.OK.phrase,
                ),
                HTTPStatus.OK,
            )
        except Exception as e:
            app.logger.error(
                f"Error creating KYC payment intent: {str(e)}",
                exc_info=True,
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to create payment intent: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/payments/webhook", methods=["POST"])
    async def payments_webhook(self):
        """
        Processes incoming Stripe webhook events.

        This method performs the following steps:
        1. Retrieves the raw request body and Stripe signature from headers.
        2. Constructs a Stripe Event object, verifying the signature.
        3. Handles 'payment_intent.succeeded' events.
        4. Extracts relevant information (e.g., ticket_id from metadata).
        5. Updates the ticket status in SurrealDB.
        6. Returns a 200 OK response to Stripe.
        """
        app.logger.info("Received webhook request.")

        # Get the raw request body
        payload = await request.get_data()
        # Get the Stripe signature from the header
        sig_header = request.headers.get("STRIPE_SIGNATURE") or request.headers.get(
            "Stripe-Signature"
        )

        event = None

        try:
            # Construct the Stripe event, verifying the signature
            # This is crucial for security to ensure the event is from Stripe
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
            app.logger.info(
                f"Stripe event constructed successfully. Type: {event.type}"
            )
        except ValueError as e:
            # Invalid payload
            app.logger.error(f"Invalid payload: {e}")
            return jsonify({"error": "Invalid payload"}), 400
        except stripe.SignatureVerificationError as e:
            # Invalid signature
            app.logger.error(f"Invalid signature: {e}")
            return jsonify({"error": "Invalid signature"}), 400
        except Exception as e:
            # Catch any other unexpected errors during event construction
            app.logger.error(f"Unexpected error constructing event: {e}")
            return jsonify({"error": "Internal server error"}), 500

        # Handle the event
        if event["type"] == "payment_intent.succeeded":
            payment_intent = event.data.object
            app.logger.info(f"PaymentIntent was successful: {payment_intent['id']}")

            # Extract ticket_id from payment_intent metadata
            # This metadata was set when creating the PaymentIntent in /create-payment-intent
            metadata = payment_intent.get("metadata")

            if "ticket_count" in metadata:
                ticket_count, user_id, event_id = (
                    int(metadata.get("ticket_count")),
                    metadata.get("user_id"),
                    metadata.get("event_id"),
                )

                for i in range(ticket_count):
                    app.logger.info(
                        f"Processing ticket {i + 1} for PaymentIntent {payment_intent['id']} | User ID: {user_id}"
                    )
                    # Create ticket in DB
                    await self.conn._create_ticket({"user": user_id, "event": event_id})
                    app.logger.info(
                        f"Ticket created for user {user_id} and event {event_id}."
                    )

                # Register the user as attending the event
                await self.conn.create_attendance(
                    {
                        "user": user_id,
                        "event": event_id,
                        "status": "paid",
                    }
                )
                app.logger.info(
                    f"User {user_id} registered as attending event {event_id}."
                )
                # Here you might send a confirmation email or notification to the user

            elif "type" in metadata and metadata["type"] == "KYC_PAYMENT":
                user_id = metadata.get("user_id")
                app.logger.info(f"KYC payment successful for user {user_id}.")
                data = {}
                data["id"] = user_id
                data["kyc_payment_status"] = True
                # Update the user's KYC status in the database
                await self.conn._update_user(data)
                app.logger.info(f"User {user_id} KYC status updated to 'verified'.")
            else:
                app.logger.warning(
                    f"No ticket data found in metadata for PaymentIntent {payment_intent['id']}. Cannot create ticket."
                )

        elif event["type"] == "payment_intent.payment_failed":
            payment_intent = event.data.object
            app.logger.warning(f"PaymentIntent failed: {payment_intent['id']}")
            # TODO: Implement failed payment handling (ticket status update, user notification)

        else:
            # Log other event types that you might not be handling explicitly
            app.logger.info(f"Unhandled event type: {event['type']}")

        # Return a 200 OK response to Stripe to acknowledge receipt of the event
        return jsonify({"status": "success"}), 200
