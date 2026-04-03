from datetime import datetime
import os
import stripe
import orjson as json
import hmac
import hashlib

from typing import Dict, Any, Optional
from http import HTTPStatus

from quart import (
    current_app as app,
    request,
    jsonify,
)
from payments.src.connectors import PaymentsDB
from shared.classful import route, QuartClassful
from shared.utils import get_client_ip, api_response, api_error, generate_signed_url
from shared.utils.paystack_client import PaystackClient
from shared.workers.resend import ResendClient
from shared.workers.novu import NotificationManager
from shared.kpi import BusinessMetrics

from quart_jwt_extended import jwt_required, get_jwt_identity
from aiocache import cached

import stripe

STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PUB_KEY = os.environ.get("STRIPE_PUB_KEY", "")
STRIPE_PRIV_KEY = os.environ.get("STRIPE_PRIV_KEY", "")
PAYMENT_WEBHOOK_URL = os.environ.get("PAYMENT_WEBHOOK_URL", "")
HOST_KYC_PRICE = os.environ.get("HOST_KYC_PRICE", 10.00)

PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_PLATFORM_FEE = float(os.environ.get("PAYSTACK_PLATFORM_FEE", "3.0"))

stripe.api_key = STRIPE_PRIV_KEY

if not STRIPE_WEBHOOK_SECRET or not STRIPE_PUB_KEY or not STRIPE_PRIV_KEY:
    raise ValueError(
        "Stripe webhook secret and API keys must be set in environment variables."
    )

if not PAYSTACK_SECRET_KEY or not PAYSTACK_PUBLIC_KEY:
    raise ValueError(
        "Paystack secret and public keys must be set in environment variables."
    )


class BaseView(QuartClassful):

    def __init__(self):
        self.conn: PaymentsDB = app.conn
        self.redis = app.redis
        self.stripe_client: Optional[stripe.StripeClient] = stripe.StripeClient(STRIPE_PRIV_KEY)
        self.paystack_client: Optional[PaystackClient] = PaystackClient(PAYSTACK_SECRET_KEY)
        self.resend_client: Optional[ResendClient] = None
        try:
            self.resend_client = ResendClient()
        except ValueError as e:
            app.logger.warning(f"ResendClient not initialized: {e}")
        self._notification_manager = NotificationManager()
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
                            "charge.refunded",
                            "payout.paid",
                        ],
                        "description": "Webhook for payment intents",
                    }
                )
                app.logger.info("Webhook endpoint created successfully.")
            return webhook_endpoints

    async def _send_tickets_email(
        self,
        to_email: str,
        user_name: str,
        event_id: str,
        is_guest: bool = True,
    ):
        """
        Shared helper to fetch ticket details and send the ticket email.
        Handles both guest (by email) and authenticated (by user_id) flows.
        Fetches event media and signs the first image for the email banner.
        """
        if not self.resend_client:
            return
        try:
            if is_guest:
                ticket_details = await self.conn._get_ticket_details_by_email(to_email, event_id)
            else:
                ticket_details = await self.conn._get_ticket_details_by_user(to_email, event_id)
                if ticket_details and ticket_details[0].get("user", {}).get("email"):
                    to_email = ticket_details[0]["user"]["email"]
                else:
                    app.logger.warning(f"No email found for user {to_email}, skipping ticket email")
                    return

            if not ticket_details:
                app.logger.warning(f"No ticket details found for {to_email} on event {event_id}")
                return

            first_ticket = ticket_details[0]
            event_data = first_ticket.get("event", {})

            if not is_guest:
                user_data = first_ticket.get("user", {})
                user_name = (
                    f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip()
                    or to_email.split('@')[0]
                )

            event_title = event_data.get("title", "Event")
            event_time = str(event_data.get("time", "TBA"))
            event_location = event_data.get("location", {}).get("address", "Location TBA")
            event_duration = event_data.get("duration", 60)

            # Extract organizer name
            organizer = first_ticket.get("organizer", {}) or {}
            organizer_name = (
                organizer.get("organization_name")
                or f"{organizer.get('first_name', '')} {organizer.get('last_name', '')}".strip()
                or None
            )

            # Extract tier info from first ticket (all tickets in one purchase share the same tier)
            tier = first_ticket.get("tier") or {}
            tier_name = tier.get("name") if tier else None
            tier_price = tier.get("price") if tier else None
            event_price = event_data.get("price", 0)
            unit_price = tier_price if tier_price is not None else event_price

            # Fetch event media and sign the first image for the email banner
            event_image_url = None
            try:
                full_event = await self.conn._fetch(event_id)
                if full_event:
                    media_list = full_event.get("media", [])
                    if media_list and len(media_list) > 0:
                        filename = media_list[0].get("filename")
                        if filename:
                            signed_urls = await generate_signed_url([filename])
                            event_image_url = signed_urls.get(filename)
            except Exception as media_err:
                app.logger.warning(f"Failed to fetch/sign event media for email: {media_err}")

            await self.resend_client.send_ticket_email(
                to_email=to_email,
                user_name=user_name,
                event_title=event_title,
                event_time=event_time,
                event_location=event_location,
                tickets=ticket_details,
                event_duration=event_duration,
                organizer_name=organizer_name,
                tier_name=tier_name,
                unit_price=unit_price,
                event_image_url=event_image_url,
            )
            app.logger.info(f"Ticket email sent to {to_email} for event {event_id}")
        except Exception as email_err:
            app.logger.error(
                f"Failed to send ticket email: {str(email_err)}",
                exc_info=True
            )

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
        self, amount: int, user_id, event_id, ticket_count: int = 1, ip_address: str = "127.0.0.1", host_stripe_account_id: str = None, coupon_code: Optional[str] = None, tier_id: Optional[str] = None, guest_name: Optional[str] = None
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
            total_amount = total_amount * (1 - COUPON.percent_off / 100)

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
        metadata = {
            "user_id": user_id,
            "ticket_count": str(ticket_count),
            "event_id": event_id,
            "tax_calculation_id": CALCULATION.id,  # Store for reference
        }
        if tier_id:
            metadata["tier_id"] = tier_id
        if guest_name:
            metadata["guest_name"] = guest_name

        payment_params = {
            "amount": CALCULATION.amount_total,  # Total includes tax
            "currency": "usd",
            "metadata": metadata,
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

    async def create_payment_paystack_transaction(
        self,
        amount: float,
        user_id: str,
        event_id: str,
        user_email: str,
        ticket_count: int = 1,
        host_paystack_subaccount: Optional[str] = None,
        tier_id: Optional[str] = None,
        guest_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a Paystack transaction for ticket purchase.
        Similar to Stripe payment intent but using Paystack's transaction API.

        Args:
            amount: Amount in the base currency (e.g., 100 for ₦100)
            user_id: User ID making the purchase
            event_id: Event ID for the purchase
            user_email: User's email address
            ticket_count: Number of tickets
            host_paystack_subaccount: Host's Paystack subaccount code for split payments
            tier_id: Optional ticket tier ID
            guest_name: Optional guest name

        Returns:
            Dict with authorization_url, access_code, reference, etc.
        """
        if not self.paystack_client:
            raise ValueError("Paystack client is not initialized.")

        # Convert to kobo (smallest unit)
        amount_in_kobo = int(amount * 100)

        app.logger.debug(
            f"Creating Paystack transaction for user {user_id} with amount {amount_in_kobo} kobo for event {event_id}"
        )

        metadata = {
            "user_id": user_id,
            "event_id": event_id,
            "ticket_count": ticket_count,
        }
        if tier_id:
            metadata["tier_id"] = tier_id
        if guest_name:
            metadata["guest_name"] = guest_name

        # Initialize transaction with Paystack
        transaction = await self.paystack_client.initialize_transaction(
            amount=amount_in_kobo,
            email=user_email,
            metadata=metadata,
            subaccount=host_paystack_subaccount,
            bearer="subaccount" if host_paystack_subaccount else "account",
        )

        if not transaction.get("status"):
            raise ValueError(f"Failed to initialize Paystack transaction: {transaction}")

        app.logger.info(
            f"Paystack transaction created: {transaction['data']['reference']} "
            f"for user {user_id} on event {event_id}"
        )

        return transaction["data"]

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

    @route("/payments/<event_id>/public-intent", methods=["POST"])
    async def create_public_intent(self, event_id: str):
        """Create payment intent for guest ticket purchase (no auth required)"""
        try:
            data: dict = await request.get_json()
            email = data.get("email", "").strip().lower()
            guest_name = data.get("name", "").strip()
            ticket_count = data.get("ticket_count", 1)

            if not email:
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="Email address is required",
                        status=status_code.phrase
                    ),
                    status_code,
                )

            if not isinstance(ticket_count, int) or ticket_count < 1:
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="Ticket count must be a positive integer",
                        status=status_code.phrase
                    ),
                    status_code,
                )

            if ticket_count > 100:
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="Maximum 100 tickets per transaction",
                        status=status_code.phrase
                    ),
                    status_code,
                )

            event = await self.conn._fetch(event_id)
            if not event:
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(message="Event not found", status=status_code.phrase),
                    status_code,
                )
            
            host_data = event.get("host", {})
            host_stripe_account_id = host_data.get("stripe_account_id", "")

            # Resolve tier if provided
            tier_id = data.get("tier_id")
            ticket_price = event.get("price", 0)
            if tier_id:
                try:
                    tier = await self.conn.check_tier_availability(tier_id, ticket_count)
                    ticket_price = tier.get("price", ticket_price)
                except ValueError as e:
                    return (
                        jsonify(message=str(e), status=HTTPStatus.BAD_REQUEST.phrase),
                        HTTPStatus.BAD_REQUEST,
                    )
            
            if ticket_price > 0 and not host_stripe_account_id:
                app.logger.warning(
                    f"Event {event_id} is paid but host {host_data.get('id')} has no Stripe account"
                )

            # Handle free events / free tiers
            if ticket_price == 0:
                app.logger.info(f"Processing free event registration for guest {email}")

                # Idempotency guard for free registrations — prevents duplicate
                # tickets from double-taps or retried requests.
                free_key = f"free_reg:{event_id}:{email}"
                if not await self.redis.set(free_key, "1", nx=True, ex=3600):
                    return (
                        jsonify(
                            data={"free": True, "event_id": event_id},
                            message="Registration already processed.",
                            status=HTTPStatus.OK.phrase,
                        ),
                        HTTPStatus.OK,
                    )

                ticket_data = {"guest_email": email, "event": event_id}
                if guest_name:
                    ticket_data["guest_name"] = guest_name
                if tier_id:
                    ticket_data["tier"] = tier_id
                for i in range(ticket_count):
                    await self.conn._create_ticket(ticket_data.copy())

                if tier_id:
                    await self.conn.increment_tier_sold_count(tier_id, ticket_count)
                await self.conn.increment_attendee_count(event_id, ticket_count)
                BusinessMetrics.TICKET_PURCHASES.labels(payment_provider="stripe").inc(ticket_count)

                await self._send_tickets_email(
                    to_email=email,
                    user_name=guest_name or email.split('@')[0],
                    event_id=event_id,
                    is_guest=True,
                )

                return (
                    jsonify(
                        data={
                            "free": True,
                            "event_id": event_id,
                            "ticket_count": ticket_count,
                            "amount": 0,
                            "currency": "usd"
                        },
                        message="Tickets issued successfully.",
                        status=HTTPStatus.OK.phrase,
                    ),
                    HTTPStatus.OK,
                )

            intent = await self.create_payment_stripe_intent(
                amount=ticket_price,
                user_id=email,
                event_id=event_id,
                ticket_count=ticket_count,
                ip_address=get_client_ip(request),
                host_stripe_account_id=host_stripe_account_id if host_stripe_account_id else None,
                coupon_code=data.get("coupon_code", ""),
                tier_id=tier_id,
                guest_name=guest_name if guest_name else None
            )

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
                f"Error creating public payment intent for event {event_id}: {str(e)}",
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

            # Resolve tier if provided
            tier_id = data.get("tier_id")
            ticket_price = event.get("price", 0)
            if tier_id:
                try:
                    tier = await self.conn.check_tier_availability(tier_id, ticket_count)
                    ticket_price = tier.get("price", ticket_price)
                except ValueError as e:
                    return (
                        jsonify(message=str(e), status=HTTPStatus.BAD_REQUEST.phrase),
                        HTTPStatus.BAD_REQUEST,
                    )
            
            # Validate host has completed Stripe onboarding for paid events
            if ticket_price > 0 and not host_stripe_account_id:
                app.logger.warning(
                    f"Event {event_id} is paid but host {host_data.get('id')} has no Stripe account"
                )
            
            # Create a stripe payment intent
            intent = await self.create_payment_stripe_intent(
                amount=ticket_price,
                user_id=user_id,
                event_id=event_id,
                ticket_count=ticket_count,
                ip_address=get_client_ip(request),
                host_stripe_account_id=host_stripe_account_id if host_stripe_account_id else None,
                coupon_code=coupon_code,
                tier_id=tier_id
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
            app.logger.warning(f"Events count: {events_count}")
            if events_count < 110: # Apply coupon for first 110 events
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

    @route("/payments/<event_id>/public-paystack-intent", methods=["POST"])
    async def create_public_paystack_intent(self, event_id: str):
        """Create Paystack transaction for guest ticket purchase (no auth required)"""
        try:
            data: dict = await request.get_json()
            email = data.get("email", "").strip().lower()
            guest_name = data.get("name", "").strip()
            ticket_count = data.get("ticket_count", 1)

            if not email:
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="Email address is required",
                        status=status_code.phrase
                    ),
                    status_code,
                )

            if not isinstance(ticket_count, int) or ticket_count < 1:
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="Ticket count must be a positive integer",
                        status=status_code.phrase
                    ),
                    status_code,
                )

            if ticket_count > 100:
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="Maximum 100 tickets per transaction",
                        status=status_code.phrase
                    ),
                    status_code,
                )

            event = await self.conn._fetch(event_id)
            if not event:
                status_code = HTTPStatus.NOT_FOUND
                return (
                    jsonify(message="Event not found", status=status_code.phrase),
                    status_code,
                )

            host_data = event.get("host", {})
            host_paystack_subaccount = host_data.get("paystack_subaccount_id", "")

            # Resolve tier if provided
            tier_id = data.get("tier_id")
            ticket_price = event.get("price", 0)
            if tier_id:
                try:
                    tier = await self.conn.check_tier_availability(tier_id, ticket_count)
                    ticket_price = tier.get("price", ticket_price)
                except ValueError as e:
                    return (
                        jsonify(message=str(e), status=HTTPStatus.BAD_REQUEST.phrase),
                        HTTPStatus.BAD_REQUEST,
                    )

            if ticket_price > 0 and not host_paystack_subaccount:
                app.logger.warning(
                    f"Event {event_id} is paid but host {host_data.get('id')} has no Paystack subaccount"
                )

            # Handle free events / free tiers
            if ticket_price == 0:
                app.logger.info(f"Processing free event registration for guest {email}")

                free_key = f"free_reg:{event_id}:{email}"
                if not await self.redis.set(free_key, "1", nx=True, ex=3600):
                    return (
                        jsonify(
                            data={"free": True, "event_id": event_id},
                            message="Registration already processed.",
                            status=HTTPStatus.OK.phrase,
                        ),
                        HTTPStatus.OK,
                    )

                ticket_data = {"guest_email": email, "event": event_id}
                if guest_name:
                    ticket_data["guest_name"] = guest_name
                if tier_id:
                    ticket_data["tier"] = tier_id
                for i in range(ticket_count):
                    await self.conn._create_ticket(ticket_data.copy())

                if tier_id:
                    await self.conn.increment_tier_sold_count(tier_id, ticket_count)
                await self.conn.increment_attendee_count(event_id, ticket_count)
                BusinessMetrics.TICKET_PURCHASES.labels(payment_provider="paystack").inc(ticket_count)

                await self._send_tickets_email(
                    to_email=email,
                    user_name=guest_name or email.split('@')[0],
                    event_id=event_id,
                    is_guest=True,
                )

                return (
                    jsonify(
                        data={
                            "free": True,
                            "event_id": event_id,
                            "ticket_count": ticket_count,
                            "amount": 0,
                            "currency": "NGN"
                        },
                        message="Tickets issued successfully.",
                        status=HTTPStatus.OK.phrase,
                    ),
                    HTTPStatus.OK,
                )

            transaction = await self.create_payment_paystack_transaction(
                amount=ticket_price,
                user_id=email,
                event_id=event_id,
                user_email=email,
                ticket_count=ticket_count,
                host_paystack_subaccount=host_paystack_subaccount if host_paystack_subaccount else None,
                tier_id=tier_id,
                guest_name=guest_name if guest_name else None,
            )

            return (
                jsonify(
                    data={
                        "authorization_url": transaction.get("authorization_url"),
                        "access_code": transaction.get("access_code"),
                        "reference": transaction.get("reference"),
                        "pub_key": PAYSTACK_PUBLIC_KEY,
                        "amount": transaction.get("amount"),
                        "currency": transaction.get("currency", "NGN"),
                        "event_id": event_id,
                    },
                    message="Paystack transaction initialized successfully.",
                    status=HTTPStatus.OK.phrase,
                ),
                HTTPStatus.OK,
            )
        except Exception as e:
            app.logger.error(
                f"Error creating public Paystack transaction for event {event_id}: {str(e)}",
                exc_info=True,
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to create Paystack transaction: {str(e)}",
                    status=status_code.phrase,
                ),
                status_code,
            )

    @route("/payments/<event_id>/create-paystack-intent", methods=["POST"])
    @jwt_required
    async def create_paystack_intent(self, event_id: str):
        """Create Paystack transaction for a user & event"""
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

            # Get user email from JWT or request
            user_email = data.get("email")
            if not user_email:
                status_code = HTTPStatus.BAD_REQUEST
                return (
                    jsonify(
                        message="User email is required",
                        status=status_code.phrase
                    ),
                    status_code,
                )

            # Get host's Paystack subaccount if available
            host_data = event.get("host", {})
            host_paystack_subaccount = host_data.get("paystack_subaccount_id", "")

            # Resolve tier if provided
            tier_id = data.get("tier_id")
            ticket_price = event.get("price", 0)
            if tier_id:
                try:
                    tier = await self.conn.check_tier_availability(tier_id, ticket_count)
                    ticket_price = tier.get("price", ticket_price)
                except ValueError as e:
                    return (
                        jsonify(message=str(e), status=HTTPStatus.BAD_REQUEST.phrase),
                        HTTPStatus.BAD_REQUEST,
                    )

            if ticket_price > 0 and not host_paystack_subaccount:
                app.logger.warning(
                    f"Event {event_id} is paid but host {host_data.get('id')} has no Paystack subaccount"
                )

            # Create Paystack transaction
            transaction = await self.create_payment_paystack_transaction(
                amount=ticket_price,
                user_id=user_id,
                event_id=event_id,
                user_email=user_email,
                ticket_count=ticket_count,
                host_paystack_subaccount=host_paystack_subaccount if host_paystack_subaccount else None,
                tier_id=tier_id,
            )

            # Return transaction data to frontend
            return (
                jsonify(
                    data={
                        "authorization_url": transaction.get("authorization_url"),
                        "access_code": transaction.get("access_code"),
                        "reference": transaction.get("reference"),
                        "pub_key": PAYSTACK_PUBLIC_KEY,
                        "amount": transaction.get("amount"),
                        "currency": transaction.get("currency", "NGN"),
                        "event_id": event_id,
                    },
                    message="Paystack transaction initialized successfully.",
                    status=HTTPStatus.OK.phrase,
                ),
                HTTPStatus.OK,
            )
        except Exception as e:
            app.logger.error(
                f"Error creating Paystack transaction for event {event_id}: {str(e)}",
                exc_info=True,
            )
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            return (
                jsonify(
                    message=f"Failed to create Paystack transaction: {str(e)}",
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
            return api_error("Invalid payload", HTTPStatus.BAD_REQUEST)
        except stripe.SignatureVerificationError as e:
            # Invalid signature
            app.logger.error(f"Invalid signature: {e}")
            return api_error("Invalid signature", HTTPStatus.BAD_REQUEST)
        except Exception as e:
            # Catch any other unexpected errors during event construction
            app.logger.error(f"Unexpected error constructing event: {e}")
            return api_error("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)

        # Handle the event
        if event["type"] == "payment_intent.succeeded":
            payment_intent = event.data.object
            payment_intent_id = payment_intent["id"]
            app.logger.info(f"PaymentIntent was successful: {payment_intent_id}")

            # ── Idempotency guard ─────────────────────────────────────────────
            # Stripe guarantees at-least-once delivery and retries on any
            # non-2xx or timeout. Without this guard a retry creates a full
            # duplicate set of tickets for real money already charged.
            # TTL 24 h covers all realistic retry windows.
            idempotency_key = f"stripe_webhook:{payment_intent_id}"
            if not await self.redis.set(idempotency_key, "1", nx=True, ex=86400):
                app.logger.info(f"Duplicate Stripe webhook ignored: {payment_intent_id}")
                return api_response("Webhook received", HTTPStatus.OK, data={"status": "success"})

            metadata = payment_intent.get("metadata")

            if "ticket_count" in metadata:
                ticket_count = int(metadata.get("ticket_count"))
                user_or_email = metadata.get("user_id")
                event_id = metadata.get("event_id")
                tier_id = metadata.get("tier_id")
                guest_name = metadata.get("guest_name")

                is_guest = "@" in user_or_email

                if is_guest:
                    app.logger.info(f"Processing guest purchase for email: {user_or_email}")
                    for i in range(ticket_count):
                        ticket_data = {
                            "guest_email": user_or_email,
                            "event": event_id
                        }
                        if guest_name:
                            ticket_data["guest_name"] = guest_name
                        if tier_id:
                            ticket_data["tier"] = tier_id
                        await self.conn._create_ticket(ticket_data)
                        app.logger.info(f"Guest ticket {i+1} created for {user_or_email}")
                else:
                    app.logger.info(f"Processing authenticated purchase for user: {user_or_email}")
                    for i in range(ticket_count):
                        ticket_data = {
                            "user": user_or_email,
                            "event": event_id
                        }
                        if tier_id:
                            ticket_data["tier"] = tier_id
                        await self.conn._create_ticket(ticket_data)
                        app.logger.info(f"Ticket {i+1} created for user {user_or_email}")

                    await self.conn.create_attendance({
                        "user": user_or_email,
                        "event": event_id,
                        "status": "paid",
                    })
                    app.logger.info(f"User {user_or_email} registered as attending event {event_id}")

                BusinessMetrics.TICKET_PURCHASES.labels(payment_provider="stripe").inc(ticket_count)

                await self._send_tickets_email(
                    to_email=user_or_email,
                    user_name=guest_name or user_or_email.split('@')[0],
                    event_id=event_id,
                    is_guest=is_guest,
                )

                # Notify the event host about the ticket purchase (non-critical)
                event_data = None
                try:
                    event_data = await self.conn._fetch(event_id)
                    if event_data:
                        host = event_data.get("host", {})
                        host_id = host.get("id", "") if isinstance(host, dict) else ""
                        if host_id:
                            host_id = str(host_id).split(":")[-1]
                            buyer_display = guest_name or user_or_email.split('@')[0]
                            await self._notification_manager.send_ticket_purchase_host_notification(
                                host_subscriber_id=host_id,
                                buyer_name=buyer_display,
                                event_name=event_data.get("title", "your event"),
                                event_id=event_id,
                                ticket_count=ticket_count,
                                total_amount=payment_intent.get("amount", 0) / 100,
                                currency=payment_intent.get("currency", "usd").upper(),
                            )
                except Exception as host_notify_err:
                    app.logger.error(f"Host notification failed (non-blocking): {host_notify_err}")

                # Push-notify the buyer (authenticated users only)
                if not is_guest:
                    try:
                        evt_title = event_data.get("title", "your event")
                        await self._notification_manager.send_ticket_purchase_buyer_notification(
                            buyer_subscriber_id=user_or_email,
                            event_name=evt_title,
                            event_id=event_id,
                            ticket_count=ticket_count,
                            total_amount=payment_intent.get("amount", 0) / 100,
                            currency=payment_intent.get("currency", "usd").upper(),
                        )
                    except Exception as buyer_err:
                        app.logger.error(f"Buyer notification failed (non-blocking): {buyer_err}")

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

        elif event["type"] == "charge.refunded":
            charge = event.data.object
            metadata = charge.get("metadata", {})
            user_id = metadata.get("user_id")
            event_id = metadata.get("event_id")
            event_name = metadata.get("event_name", "your event")
            amount = charge.get("amount_refunded", 0) / 100
            currency = charge.get("currency", "usd")
            app.logger.info(f"Charge refunded: {charge.get('id')} for user {user_id}")
            if user_id:
                try:
                    await self._notification_manager.send_ticket_refund(
                        subscriber_id=user_id,
                        event_name=event_name,
                        event_id=event_id or "",
                        amount=amount,
                        currency=currency,
                    )
                except Exception as refund_notif_err:
                    app.logger.error(f"Refund notification failed (non-blocking): {refund_notif_err}")

        elif event["type"] == "payout.paid":
            payout = event.data.object
            stripe_account_id = event.get("account")
            amount = payout.get("amount", 0) / 100
            currency = payout.get("currency", "usd")
            arrival_date = str(payout.get("arrival_date", ""))
            app.logger.info(f"Payout paid: {payout.get('id')} account={stripe_account_id}")
            if stripe_account_id:
                try:
                    host_rows = await self.conn.pool.execute_query(
                        "SELECT VALUE string::split(string::concat(id, ''), ':')[1] "
                        "FROM ONLY users WHERE stripe_account_id = $acct LIMIT 1",
                        {"acct": stripe_account_id},
                    )
                    host_id = host_rows[0] if host_rows else None
                    if host_id:
                        await self._notification_manager.send_payout_processed(
                            host_subscriber_id=host_id,
                            amount=amount,
                            currency=currency,
                            arrival_date=arrival_date,
                        )
                except Exception as payout_notif_err:
                    app.logger.error(f"Payout notification failed (non-blocking): {payout_notif_err}")

        else:
            # Log other event types that you might not be handling explicitly
            app.logger.info(f"Unhandled event type: {event['type']}")

        # Return a 200 OK response to Stripe to acknowledge receipt of the event
        return api_response("Webhook received", HTTPStatus.OK, data={"status": "success"})

    def _verify_paystack_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify Paystack webhook signature using HMAC SHA512.

        Args:
            payload: Raw request body bytes
            signature: x-paystack-signature header value

        Returns:
            bool: True if signature is valid, False otherwise
        """
        expected_signature = hmac.new(
            PAYSTACK_SECRET_KEY.encode(),
            payload,
            hashlib.sha512
        ).hexdigest()

        return hmac.compare_digest(signature, expected_signature)

    @route("/payments/paystack-webhook", methods=["POST"])
    async def paystack_webhook(self):
        """
        Processes incoming Paystack webhook events.

        Paystack sends webhooks for successful transactions with:
        1. x-paystack-signature header (HMAC SHA512 of payload)
        2. charge.success event type
        3. Transaction reference and metadata in payload

        Flow:
        1. Verify webhook signature
        2. Extract transaction data
        3. Verify transaction status via API
        4. Create tickets and attendance records
        5. Return 200 OK to acknowledge receipt
        """
        app.logger.info("Received Paystack webhook request.")

        # Get raw payload and signature
        payload = await request.get_data()
        signature = request.headers.get("x-paystack-signature", "")

        if not signature:
            app.logger.error("Missing x-paystack-signature header")
            return api_error("Missing signature", HTTPStatus.BAD_REQUEST)

        # Verify signature
        if not self._verify_paystack_signature(payload, signature):
            app.logger.error("Invalid Paystack webhook signature")
            return api_error("Invalid signature", HTTPStatus.FORBIDDEN)

        try:
            event_data = json.loads(payload)
        except json.JSONDecodeError as e:
            app.logger.error(f"Invalid JSON payload: {e}")
            return api_error("Invalid payload", HTTPStatus.BAD_REQUEST)

        app.logger.info(f"Paystack event type: {event_data.get('event')}")

        # Handle charge.success event
        if event_data.get("event") == "charge.success":
            try:
                data = event_data.get("data", {})
                reference = data.get("reference")
                metadata = data.get("metadata", {})

                if not reference:
                    app.logger.error("Missing transaction reference in webhook")
                    return api_error("Missing reference", HTTPStatus.BAD_REQUEST)

                app.logger.info(f"Processing successful charge: {reference}")

                # ── Idempotency guard ─────────────────────────────────────────
                # Paystack retries webhooks on any non-2xx or timeout.
                # SET NX ensures only the first delivery processes tickets.
                idempotency_key = f"paystack_webhook:{reference}"
                if not await self.redis.set(idempotency_key, "1", nx=True, ex=86400):
                    app.logger.info(f"Duplicate Paystack webhook ignored: {reference}")
                    return api_response("Webhook received", HTTPStatus.OK, data={"status": "success"})

                # Verify transaction via API to confirm status
                verification = await self.paystack_client.verify_transaction(reference)

                if not verification.get("status"):
                    app.logger.error(f"Transaction verification failed: {verification}")
                    # Roll back the idempotency key so a later retry can try again
                    await self.redis.delete(idempotency_key)
                    return api_error("Verification failed", HTTPStatus.BAD_REQUEST)

                verified_data = verification.get("data", {})
                if verified_data.get("status") != "success":
                    app.logger.warning(f"Transaction {reference} status is not success: {verified_data.get('status')}")
                    return api_response("Webhook received", HTTPStatus.OK, data={"status": "success"})

                # Extract metadata
                user_or_email = metadata.get("user_id")
                event_id = metadata.get("event_id")
                ticket_count = int(metadata.get("ticket_count", 1))
                tier_id = metadata.get("tier_id")
                guest_name = metadata.get("guest_name")

                if not user_or_email or not event_id:
                    app.logger.error(f"Missing user_id or event_id in metadata: {metadata}")
                    return api_error("Missing metadata", HTTPStatus.BAD_REQUEST)

                is_guest = "@" in user_or_email

                if is_guest:
                    app.logger.info(f"Processing guest purchase for email: {user_or_email}")
                    for i in range(ticket_count):
                        ticket_data = {
                            "guest_email": user_or_email,
                            "event": event_id
                        }
                        if guest_name:
                            ticket_data["guest_name"] = guest_name
                        if tier_id:
                            ticket_data["tier"] = tier_id
                        await self.conn._create_ticket(ticket_data)
                        app.logger.info(f"Guest ticket {i+1} created for {user_or_email}")
                else:
                    app.logger.info(f"Processing authenticated purchase for user: {user_or_email}")
                    for i in range(ticket_count):
                        ticket_data = {
                            "user": user_or_email,
                            "event": event_id
                        }
                        if tier_id:
                            ticket_data["tier"] = tier_id
                        await self.conn._create_ticket(ticket_data)
                        app.logger.info(f"Ticket {i+1} created for user {user_or_email}")

                    await self.conn.create_attendance({
                        "user": user_or_email,
                        "event": event_id,
                        "status": "paid",
                    })
                    app.logger.info(f"User {user_or_email} registered as attending event {event_id}")

                BusinessMetrics.TICKET_PURCHASES.labels(payment_provider="paystack").inc(ticket_count)

                await self._send_tickets_email(
                    to_email=user_or_email,
                    user_name=guest_name or user_or_email.split('@')[0],
                    event_id=event_id,
                    is_guest=is_guest,
                )

                # Notify the event host about the ticket purchase (non-critical)
                ps_event_data = None
                try:
                    ps_event_data = await self.conn._fetch(event_id)
                    if ps_event_data:
                        host = ps_event_data.get("host", {})
                        host_id = host.get("id", "") if isinstance(host, dict) else ""
                        if host_id:
                            host_id = str(host_id).split(":")[-1]
                            buyer_display = guest_name or user_or_email.split('@')[0]
                            await self._notification_manager.send_ticket_purchase_host_notification(
                                host_subscriber_id=host_id,
                                buyer_name=buyer_display,
                                event_name=ps_event_data.get("title", "your event"),
                                event_id=event_id,
                                ticket_count=ticket_count,
                                total_amount=verified_data.get("amount", 0) / 100,
                                currency=verified_data.get("currency", "NGN").upper(),
                            )
                except Exception as host_notify_err:
                    app.logger.error(f"Host notification failed (non-blocking): {host_notify_err}")

                # Push-notify the buyer (authenticated users only)
                if not is_guest:
                    try:
                        ps_evt_title = ps_event_data.get("title", "your event") if ps_event_data else "your event"
                        await self._notification_manager.send_ticket_purchase_buyer_notification(
                            buyer_subscriber_id=user_or_email,
                            event_name=ps_evt_title,
                            event_id=event_id,
                            ticket_count=ticket_count,
                            total_amount=verified_data.get("amount", 0) / 100,
                            currency=verified_data.get("currency", "NGN").upper(),
                        )
                    except Exception as buyer_err:
                        app.logger.error(f"Buyer notification failed (non-blocking): {buyer_err}")

            except Exception as e:
                app.logger.error(
                    f"Error processing Paystack webhook: {str(e)}",
                    exc_info=True,
                )
                # Return 200 to prevent Paystack from retrying
                return api_response("Webhook received", HTTPStatus.OK, data={"status": "success"})

        else:
            app.logger.info(f"Unhandled Paystack event: {event_data.get('event')}")

        # Return 200 OK to acknowledge receipt
        return api_response("Webhook received", HTTPStatus.OK, data={"status": "success"})