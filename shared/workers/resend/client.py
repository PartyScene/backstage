import rusty_req
import orjson as json
import os
import logging
from datetime import datetime
from urllib.parse import quote
from typing import Dict, Any, List, Optional
from shared.utils import parse_rusty_req_response

logger = logging.getLogger(__name__)


class ResendClient:
	def __init__(self, api_key: Optional[str] = None):
		self.api_key = api_key or os.environ.get("RESEND_API_KEY")
		if not self.api_key:
			raise ValueError("RESEND_API_KEY must be set in environment or passed to constructor")
		
		self.headers = {
			"Authorization": f"Bearer {self.api_key}",
			"Content-Type": "application/json",
		}
		self.base_url = "https://api.resend.com"

	async def send_email(
		self,
		from_email: str,
		to: List[str],
		subject: str,
		html: str,
		text: Optional[str] = None,
		reply_to: Optional[str] = None,
		attachments: Optional[List[Dict[str, Any]]] = None,
	) -> Dict[str, Any]:
		try:
			payload = {
				"from": from_email,
				"to": to if isinstance(to, list) else [to],
				"subject": subject,
				"html": html,
			}
			
			if text:
				payload["text"] = text
			if reply_to:
				payload["reply_to"] = reply_to
			if attachments:
				payload["attachments"] = attachments

			response = await rusty_req.fetch_single(
				url=f"{self.base_url}/emails",
				method="POST",
				headers=self.headers,
				params=payload,
				timeout=30.0,
			)
			
			result = parse_rusty_req_response(response, expected_status=(200, 201))
			logger.info(f"Email sent successfully: {result.get('id')}")
			return result
		except Exception as e:
			logger.error(f"Failed to send email via Resend: {e}")
			raise

	@staticmethod
	def _format_event_time(raw_time: str) -> str:
		"""Format ISO datetime to human-readable string."""
		try:
			dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
			return dt.strftime("%A, %B %-d, %Y at %-I:%M %p %Z").strip()
		except (ValueError, AttributeError):
			try:
				dt = datetime.fromisoformat(str(raw_time))
				return dt.strftime("%A, %B %d, %Y at %I:%M %p").strip()
			except Exception:
				return str(raw_time) if raw_time else "TBA"

	@staticmethod
	def _build_gcal_url(
		title: str, start_time: str, duration_min: int, location: str
	) -> str:
		"""Build a Google Calendar event URL."""
		try:
			dt = datetime.fromisoformat(
				start_time.replace("Z", "+00:00")
			)
			start = dt.strftime("%Y%m%dT%H%M%SZ")
			from datetime import timedelta
			end_dt = dt + timedelta(minutes=duration_min)
			end = end_dt.strftime("%Y%m%dT%H%M%SZ")
		except Exception:
			return ""
		params = (
			f"action=TEMPLATE"
			f"&text={quote(title)}"
			f"&dates={start}/{end}"
			f"&location={quote(location)}"
		)
		return f"https://calendar.google.com/calendar/render?{params}"

	async def send_ticket_email(
		self,
		to_email: str,
		user_name: str,
		event_title: str,
		event_time: str,
		event_location: str,
		tickets: List[Dict[str, Any]],
		event_duration: int = 60,
		organizer_name: Optional[str] = None,
		tier_name: Optional[str] = None,
		unit_price: Optional[float] = None,
		event_image_url: Optional[str] = None,
		from_email: str = "D from Scenes! <no-reply@mail.partyscene.app>",
	) -> Dict[str, Any]:
		formatted_time = self._format_event_time(event_time)
		gcal_url = self._build_gcal_url(
			event_title, event_time, event_duration, event_location
		)
		ticket_count = len(tickets)
		current_year = datetime.now().year

		# -- Event banner image --
		banner_html = ""
		if event_image_url:
			banner_html = f"""
	<div style="border-radius:16px 16px 0 0;overflow:hidden;line-height:0;">
		<img src="{event_image_url}" alt="{event_title}" width="600" style="width:100%;max-height:280px;object-fit:cover;display:block;" />
	</div>"""

		# -- Header (with or without banner) --
		header_radius = "0" if event_image_url else "16px 16px 0 0"

		# -- Ticket QR cards --
		ticket_rows = ""
		for ticket in tickets:
			ticket_number = ticket.get("ticket_number", "N/A")
			event_id = ticket.get("event", {}).get("id", "")
			qr_data = quote(f"DOWNLOAD:{event_id}:{ticket_number}")
			qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={qr_data}&margin=10"
			ticket_rows += f"""
				<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:12px;padding:20px;margin-bottom:16px;text-align:center;">
					<img src="{qr_code_url}" alt="QR Code for {ticket_number}" width="160" height="160" style="display:block;margin:0 auto 12px;" />
					<p style="font-family:monospace;font-size:15px;font-weight:700;color:#111827;margin:0 0 4px;">{ticket_number}</p>
				</div>"""

		# -- Google Calendar button --
		gcal_button = ""
		if gcal_url:
			gcal_button = f"""
				<a href="{gcal_url}" target="_blank" style="display:inline-block;padding:12px 24px;background:#ffffff;color:#374151;border:1px solid #d1d5db;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;">
					&#128197; Add to Google Calendar
				</a>"""

		# -- Organizer row --
		organizer_row = ""
		if organizer_name:
			organizer_row = f"""
				<tr>
					<td style="padding:6px 0;vertical-align:top;width:28px;font-size:16px;">&#127908;</td>
					<td style="padding:6px 0;font-size:15px;color:#374151;"><strong>Hosted by</strong><br>{organizer_name}</td>
				</tr>"""

		# -- Order summary --
		order_summary_html = ""
		if unit_price is not None and unit_price > 0:
			total = unit_price * ticket_count
			tier_label = f" ({tier_name})" if tier_name else ""
			order_summary_html = f"""
		<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:20px;margin:0 0 28px;">
			<h2 style="margin:0 0 14px;font-size:18px;color:#166534;">Order Summary</h2>
			<table style="width:100%;border-collapse:collapse;font-size:15px;color:#374151;">
				<tr>
					<td style="padding:4px 0;">{ticket_count} x Ticket{tier_label}</td>
					<td style="padding:4px 0;text-align:right;">{unit_price:,.2f}</td>
				</tr>
				<tr style="border-top:1px solid #bbf7d0;">
					<td style="padding:8px 0 0;font-weight:700;">Total</td>
					<td style="padding:8px 0 0;text-align:right;font-weight:700;">{total:,.2f}</td>
				</tr>
			</table>
		</div>"""
		elif unit_price == 0 or unit_price is None:
			tier_label = f" &mdash; {tier_name}" if tier_name else ""
			order_summary_html = f"""
		<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:16px 20px;margin:0 0 28px;">
			<p style="margin:0;font-size:15px;color:#166534;font-weight:600;">&#127881; {ticket_count} Free Ticket{"s" if ticket_count != 1 else ""}{tier_label}</p>
		</div>"""

		html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Your Tickets for {event_title}</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;color:#1f2937;">
<div style="max-width:600px;margin:0 auto;padding:24px 16px;">

	{banner_html}

	<!-- Header -->
	<div style="background:linear-gradient(135deg,#7c3aed 0%,#a855f7 100%);padding:32px 24px;border-radius:{header_radius};text-align:center;">
		<p style="margin:0 0 4px;font-size:13px;color:rgba(255,255,255,0.8);letter-spacing:1px;text-transform:uppercase;">PartyScene</p>
		<h1 style="color:#ffffff;margin:0;font-size:26px;font-weight:700;">Your Tickets Are Confirmed</h1>
	</div>

	<!-- Body -->
	<div style="background:#ffffff;padding:32px 24px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 16px 16px;">

		<p style="font-size:16px;margin:0 0 16px;">Hi <strong>{user_name}</strong>,</p>
		<p style="font-size:16px;margin:0 0 24px;color:#374151;">
			You're all set! {ticket_count} ticket{"s" if ticket_count != 1 else ""} for <strong>{event_title}</strong> {"are" if ticket_count != 1 else "is"} confirmed and ready.
		</p>

		<!-- Event details card -->
		<div style="background:#faf5ff;border:1px solid #e9d5ff;border-radius:12px;padding:20px;margin:0 0 28px;">
			<h2 style="margin:0 0 14px;font-size:18px;color:#6b21a8;">Event Details</h2>
			<table style="width:100%;border-collapse:collapse;">
				<tr>
					<td style="padding:6px 0;vertical-align:top;width:28px;font-size:16px;">&#128197;</td>
					<td style="padding:6px 0;font-size:15px;color:#374151;"><strong>When</strong><br>{formatted_time}</td>
				</tr>
				<tr>
					<td style="padding:6px 0;vertical-align:top;width:28px;font-size:16px;">&#128205;</td>
					<td style="padding:6px 0;font-size:15px;color:#374151;"><strong>Where</strong><br>{event_location}</td>
				</tr>
				{organizer_row}
			</table>
		</div>

		{order_summary_html}

		<!-- CTA buttons -->
		<div style="text-align:center;margin:0 0 28px;">
			{gcal_button}
		</div>

		<!-- Tickets -->
		<h2 style="font-size:18px;color:#111827;margin:0 0 16px;">Your Ticket{"s" if ticket_count != 1 else ""}</h2>
		{ticket_rows}

		<!-- Important notice -->
		<div style="background:#fefce8;border:1px solid #fde68a;border-radius:10px;padding:16px;margin:24px 0;">
			<p style="margin:0;font-size:14px;color:#854d0e;">
				<strong>How to check in:</strong> Present the QR code above at the event entrance. Save this email or screenshot your QR code{"s" if ticket_count != 1 else ""} — you'll need {"them" if ticket_count != 1 else "it"} to get in.
			</p>
		</div>

		<p style="font-size:14px;color:#6b7280;margin:24px 0 0;">
			See you there!{f" If you have questions, reach out to {organizer_name}." if organizer_name else ""}
		</p>
	</div>

	<!-- Footer -->
	<div style="text-align:center;padding:20px 0 0;">
		<p style="font-size:12px;color:#9ca3af;margin:0;">&copy; {current_year} PartyScene. All rights reserved.</p>
	</div>

</div>
</body>
</html>"""

		# -- Plain text fallback --
		text_content = f"Hi {user_name},\n\n"
		text_content += f"You're all set! {ticket_count} ticket{'s' if ticket_count != 1 else ''} for {event_title} confirmed.\n\n"
		text_content += "EVENT DETAILS\n"
		text_content += f"When: {formatted_time}\n"
		text_content += f"Where: {event_location}\n"
		if organizer_name:
			text_content += f"Hosted by: {organizer_name}\n"
		text_content += "\n"
		if unit_price is not None and unit_price > 0:
			total = unit_price * ticket_count
			tier_label = f" ({tier_name})" if tier_name else ""
			text_content += f"ORDER: {ticket_count} x Ticket{tier_label} = {total:,.2f}\n\n"
		elif tier_name:
			text_content += f"TICKET TYPE: {tier_name} (Free)\n\n"
		text_content += "YOUR TICKETS\n"
		for ticket in tickets:
			text_content += f"  - {ticket.get('ticket_number', 'N/A')}\n"
		if gcal_url:
			text_content += f"\nAdd to Google Calendar: {gcal_url}\n"
		text_content += "\nPresent your QR code at the entrance to check in.\n"
		text_content += f"\n(c) {current_year} PartyScene\n"

		return await self.send_email(
			from_email=from_email,
			to=[to_email],
			subject=f"Your Tickets for {event_title}",
			html=html_content,
			text=text_content,
		)
