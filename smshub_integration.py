import logging
from typing import Optional, List, Dict
from smshub_api import SmsHubAPI, SmsHubConfig
from config import SMSHUB_API_KEY, SMSHUB_AGENT_ID, SMSHUB_SERVER_URL
import re
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SmsHubIntegration:
    def __init__(self):
        # Remove any 'U' prefix from API key if present
        api_key = SMSHUB_API_KEY.replace('U', '') if SMSHUB_API_KEY.startswith('U') else SMSHUB_API_KEY
        
        config = SmsHubConfig(
            api_key=api_key,
            agent_id=SMSHUB_AGENT_ID,
            server_url=SMSHUB_SERVER_URL
        )
        self.api = SmsHubAPI(config)
        self.registered_modems: Dict[str, Dict] = {}  # Store registered modems
        self.sms_queue: List[Dict] = []  # Queue for SMS messages to be sent
        self.next_sms_id = 1  # Counter for SMS IDs

    def register_modem(self, port: str, phone_number: str) -> bool:
        """Register a modem."""
        try:
            # Add to registered modems
            self.registered_modems[phone_number] = {
                'port': port,
                'status': 'ready',
                'phone': phone_number,
                'last_seen': time.time()
            }
            logger.info(f"Registered modem {phone_number}")
            return True
        except Exception as e:
            logger.error(f"Failed to register modem: {e}")
            return False

    def get_modem_status(self, phone_number: str) -> str:
        """Get status of a specific modem."""
        if not phone_number:
            return 'No Phone Number'
            
        # Check if modem is registered
        if phone_number in self.registered_modems:
            return self.registered_modems[phone_number].get('status', 'Ready')
        return 'Not Registered'

    def process_message(self, modem_id: str, message: dict) -> None:
        """Process a new message from a modem."""
        try:
            # Get phone number for the modem
            modem = None
            for m in self.registered_modems.values():
                if m['port'] == modem_id:
                    modem = m
                    break

            if not modem:
                logger.error(f"No registered modem found for port {modem_id}")
                return

            # Validate phone number format
            try:
                phone = str(modem['phone'])
                if not phone.isdigit():
                    raise ValueError("Phone must be numeric")
                phone = int(phone)  # Convert to int for SMS Hub
            except (ValueError, TypeError) as e:
                logger.error(f"Invalid phone number format: {e}")
                return

            # Queue SMS for delivery to SMS Hub with proper type validation
            sms = {
                'smsId': int(self.next_sms_id),  # Ensure numeric
                'phone': phone,  # Already validated as numeric with country code
                'phoneFrom': str(message.get('sender', 'Unknown')),  # Ensure string
                'text': str(message.get('text', ''))  # Ensure string
            }
            self.next_sms_id += 1
            self.sms_queue.append(sms)

            # Try to send immediately
            self._process_sms_queue()

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def _process_sms_queue(self) -> None:
        """Process queued SMS messages with proper retry logic."""
        if not self.sms_queue:
            return

        # Try to send each SMS in the queue
        remaining_sms = []
        for sms in self.sms_queue:
            try:
                success = False
                retry_count = 0
                while not success and retry_count < 3:  # Maximum 3 retries
                    if self.api.push_sms(
                        sms_id=sms['smsId'],
                        phone=str(sms['phone']),
                        phone_from=sms['phoneFrom'],
                        text=sms['text']
                    ):
                        logger.info(f"Successfully sent SMS {sms['smsId']} to SMS Hub")
                        success = True
                    else:
                        retry_count += 1
                        if retry_count < 3:
                            logger.warning(f"Failed to send SMS {sms['smsId']}, attempt {retry_count}/3")
                            time.sleep(10)  # 10 second delay between retries
                        else:
                            logger.error(f"Failed to send SMS {sms['smsId']} after 3 attempts")
                            remaining_sms.append(sms)
            except Exception as e:
                logger.error(f"Error sending SMS {sms['smsId']}: {e}")
                remaining_sms.append(sms)

        self.sms_queue = remaining_sms