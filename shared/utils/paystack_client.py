"""
Paystack API client for transaction processing and subaccount management.
Handles payment initialization, verification, and marketplace split payments.
Uses the official paystack-sdk library with async support.
"""

import os
import asyncio
import json
from typing import Dict, Any, Optional
from functools import partial
import paystack


class PaystackClient:
	"""
	Paystack API client wrapper using the official paystack-sdk library.
	Handles transactions and subaccounts for marketplace payments.
	Wraps synchronous paystack library calls in async methods for Quart compatibility.
	"""

	def __init__(self, secret_key: Optional[str] = None):
		self.secret_key = secret_key or os.environ.get("PAYSTACK_SECRET_KEY", "")

		if not self.secret_key:
			raise ValueError("PAYSTACK_SECRET_KEY environment variable must be set")

		# Set module-level API key for paystack-sdk
		paystack.api_key = self.secret_key

	async def initialize_transaction(
		self,
		amount: int,
		email: str,
		metadata: Dict[str, Any],
		subaccount: Optional[str] = None,
		split_code: Optional[str] = None,
		bearer: str = "account",
	) -> Dict[str, Any]:
		"""
		Initialize a transaction on Paystack.
		Similar to Stripe's payment intent creation.

		Args:
			amount: Amount in kobo (smallest unit, e.g., 100 = ₦1.00)
			email: Customer email address
			metadata: Custom metadata to attach to transaction
			subaccount: Subaccount code for split payments (marketplace)
			split_code: Split payment code for automatic splitting
			bearer: Who bears the transaction fee ('account', 'subaccount')

		Returns:
			Dict with authorization_url, access_code, reference, etc.
		"""
		# Use official paystack-sdk API: paystack.Transaction.initialize()
		# Metadata must be stringified JSON according to Paystack docs
		func = partial(
			paystack.Transaction.initialize,
			email,
			amount,
			metadata=json.dumps(metadata),
			subaccount=subaccount,
			split_code=split_code,
			bearer=bearer if subaccount else None
		)
		response = await asyncio.to_thread(func)
		return response

	async def verify_transaction(self, reference: str) -> Dict[str, Any]:
		"""
		Verify a transaction using its reference.
		Returns transaction details including status and amount.

		Args:
			reference: Transaction reference from initialization

		Returns:
			Dict with transaction status, amount, customer info, etc.
		"""
		# Use official paystack-sdk API: paystack.Transaction.verify()
		func = partial(paystack.Transaction.verify, reference)
		response = await asyncio.to_thread(func)
		return response

	async def create_subaccount(
		self,
		business_name: str,
		settlement_bank: str,
		account_number: str,
		percentage_charge: float,
		description: Optional[str] = None,
	) -> Dict[str, Any]:
		"""
		Create a subaccount for a host/vendor (marketplace split payments).

		Args:
			business_name: Name of the business/host
			settlement_bank: Bank code (e.g., "058" for GTBank)
			account_number: Bank account number
			percentage_charge: Platform fee percentage (e.g., 3.0 for 3%)
			description: Optional description

		Returns:
			Dict with subaccount_code, business_name, etc.
		"""
		# Use official paystack-sdk API: paystack.Subaccount.create()
		func = partial(
			paystack.Subaccount.create,
			business_name,
			settlement_bank,
			account_number,
			percentage_charge,
			description=description
		)
		response = await asyncio.to_thread(func)
		return response

	async def get_subaccount(self, subaccount_code: str) -> Dict[str, Any]:
		"""
		Retrieve subaccount details.

		Args:
			subaccount_code: The subaccount code

		Returns:
			Dict with subaccount details
		"""
		# Use official paystack-sdk API: paystack.Subaccount.fetch()
		func = partial(paystack.Subaccount.fetch, subaccount_code)
		response = await asyncio.to_thread(func)
		return response

	async def list_subaccounts(self, per_page: int = 50, page: int = 1) -> Dict[str, Any]:
		"""
		List all subaccounts.

		Args:
			per_page: Number of records per page
			page: Page number

		Returns:
			Dict with list of subaccounts
		"""
		# Use official paystack-sdk API: paystack.Subaccount.list()
		func = partial(paystack.Subaccount.list, per_page=per_page, page=page)
		response = await asyncio.to_thread(func)
		return response

	async def create_split(
		self,
		name: str,
		type: str,
		currency: str,
		subaccounts: list,
		bearer_type: str = "account",
		bearer_subaccount: Optional[str] = None,
	) -> Dict[str, Any]:
		"""
		Create a split payment configuration.

		Args:
			name: Name of the split
			type: Type of split ('percentage' or 'flat')
			currency: Currency code (e.g., 'NGN')
			subaccounts: List of dicts with subaccount and share
			bearer_type: Who bears the transaction fee
			bearer_subaccount: Subaccount to bear the fee

		Returns:
			Dict with split_code and details
		"""
		# Use official paystack-sdk API: paystack.Split.create()
		func = partial(
			paystack.Split.create,
			name,
			type,
			currency,
			subaccounts,
			bearer_type=bearer_type,
			bearer_subaccount=bearer_subaccount
		)
		response = await asyncio.to_thread(func)
		return response

	async def get_transaction_timeline(self, reference: str) -> Dict[str, Any]:
		"""
		Get timeline/history of a transaction.

		Args:
			reference: Transaction reference

		Returns:
			Dict with transaction timeline events
		"""
		# Note: timeline is called 'event' in paystack-sdk
		func = partial(paystack.Transaction.event, reference)
		response = await asyncio.to_thread(func)
		return response
