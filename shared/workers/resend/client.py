import rusty_req
import orjson as json
import os
import logging
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

	async def send_ticket_email(
		self,
		to_email: str,
		user_name: str,
		event_title: str,
		event_time: str,
		event_location: str,
		tickets: List[Dict[str, Any]],
		from_email: str = "PartyScene <tickets@partyscene.app>",
	) -> Dict[str, Any]:
		ticket_rows = ""
		for ticket in tickets:
			ticket_number = ticket.get("ticket_number", "N/A")
			qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={ticket_number}"
			ticket_rows += f"""
			<tr>
				<td style="padding: 15px; border-bottom: 1px solid #e5e7eb;">
					<strong>{ticket_number}</strong>
				</td>
				<td style="padding: 15px; border-bottom: 1px solid #e5e7eb; text-align: center;">
					<img src="{qr_code_url}" alt="QR Code" style="width: 100px; height: 100px;" />
				</td>
			</tr>
			"""

		html_content = f"""
<!DOCTYPE html>
<html>
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Your Tickets for {event_title}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #1f2937; max-width: 600px; margin: 0 auto; padding: 20px;">
	<div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
		<h1 style="color: white; margin: 0; font-size: 28px;">🎉 Your Tickets Are Ready!</h1>
	</div>
	
	<div style="background: white; padding: 30px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 10px 10px;">
		<p style="font-size: 16px; margin-bottom: 10px;">Hi {user_name},</p>
		<p style="font-size: 16px; margin-bottom: 20px;">
			Thank you for your purchase! Here are your tickets for <strong>{event_title}</strong>.
		</p>
		
		<div style="background: #f3f4f6; padding: 20px; border-radius: 8px; margin: 20px 0;">
			<h2 style="margin-top: 0; font-size: 20px; color: #111827;">Event Details</h2>
			<p style="margin: 8px 0;"><strong>📅 When:</strong> {event_time}</p>
			<p style="margin: 8px 0;"><strong>📍 Where:</strong> {event_location}</p>
		</div>
		
		<h2 style="font-size: 20px; color: #111827; margin-top: 30px;">Your Tickets</h2>
		<table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
			<thead>
				<tr style="background: #f9fafb;">
					<th style="padding: 15px; text-align: left; border-bottom: 2px solid #e5e7eb;">Ticket Number</th>
					<th style="padding: 15px; text-align: center; border-bottom: 2px solid #e5e7eb;">QR Code</th>
				</tr>
			</thead>
			<tbody>
				{ticket_rows}
			</tbody>
		</table>
		
		<div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 20px 0; border-radius: 4px;">
			<p style="margin: 0; color: #92400e;">
				<strong>⚠️ Important:</strong> Save this email or take screenshots of your QR codes. 
				You'll need to present them at the event entrance for check-in.
			</p>
		</div>
		
		<p style="font-size: 14px; color: #6b7280; margin-top: 30px;">
			See you at the event! If you have any questions, please contact the event organizer.
		</p>
		
		<hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">
		
		<p style="font-size: 12px; color: #9ca3af; text-align: center; margin: 0;">
			© 2026 PartyScene. All rights reserved.
		</p>
	</div>
</body>
</html>
"""

		text_content = f"""
Hi {user_name},

Thank you for your purchase! Here are your tickets for {event_title}.

EVENT DETAILS
When: {event_time}
Where: {event_location}

YOUR TICKETS
"""
		for ticket in tickets:
			ticket_number = ticket.get("ticket_number", "N/A")
			text_content += f"- Ticket: {ticket_number}\n"

		text_content += """
IMPORTANT: Save this email or take screenshots of your QR codes. You'll need to present them at the event entrance for check-in.

See you at the event!

© 2026 PartyScene. All rights reserved.
"""

		return await self.send_email(
			from_email=from_email,
			to=[to_email],
			subject=f"Your Tickets for {event_title}",
			html=html_content,
			text=text_content,
		)
