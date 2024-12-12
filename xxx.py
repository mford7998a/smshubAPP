import logging
import time
import threading
import serial.tools.list_ports
import re
from typing import Dict, Optional, List
from config import config

logger = logging.getLogger(__name__)

class ModemManager:
    def __init__(self, server=None):
        self.modems: Dict[str, Dict] = {}  # port -> modem_info
        self.running = False
        self.scan_thread = None
        self.server = server  # Add server reference
        self.connected_modems = set()  # Track connected modems

    def start(self):
        """Start modem scanning."""
        self.running = True
        self.scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
        self.scan_thread.start()

    def stop(self):
        """Stop modem scanning."""
        self.running = False
        if self.scan_thread:
            self.scan_thread.join()

    def _scan_loop(self):
        """Continuously scan for modems."""
        while self.running:
            try:
                self._scan_modems()
            except Exception as e:
                logger.error(f"Error scanning modems: {e}")
            time.sleep(5)  # Scan every 5 seconds

    def _scan_modems(self):
        """Scan for USB modems."""
        try:
            current_ports = set()
            
            # List all COM ports
            logger.info("Starting modem scan...")
            for port in serial.tools.list_ports.comports():
                logger.info(f"Found port: {port.device} - {port.description}")
                
                if self._is_gsm_modem(port):
                    logger.info(f"Port {port.device} identified as GSM modem")
                    current_ports.add(port.device)
                    if port.device not in self.modems:
                        logger.info(f"Adding new modem on port {port.device}")
                        self._add_modem(port)
                else:
                    logger.debug(f"Port {port.device} is not a GSM modem")
            
            # Remove disconnected modems
            disconnected = set(self.modems.keys()) - current_ports
            for port in disconnected:
                logger.info(f"Removing disconnected modem: {port}")
                self._remove_modem(port)
                
            logger.info(f"Scan complete. Active modems: {list(self.modems.keys())}")
            
        except Exception as e:
            logger.error(f"Error in modem scan: {e}", exc_info=True)

    def _is_diagnostic_port(self, port) -> bool:
        """Check if this is a diagnostic or management port."""
        if not hasattr(port, 'description'):
            return False
            
        diagnostic_keywords = [
            'DIAGNOSTIC',
            'DIAG',
            'NMEA',
            'AT INTERFACE',
            'MANAGEMENT',
            'QCDM',
            'QXDM',
            'PCUI',
            'LOGGING',
            'DM PORT',
            'ADB',
            'QDLoader'
        ]
        
        description = port.description.upper()
        return any(keyword in description for keyword in diagnostic_keywords)

    def _is_gsm_modem(self, port) -> bool:
        """Check if this is a Franklin T9 modem."""
        try:
            # Log port details
            logger.debug(f"Checking if port is Franklin T9 modem: {port.device}")
            logger.debug(f"Port description: {port.description}")
            logger.debug(f"Port manufacturer: {port.manufacturer}")
            logger.debug(f"Port product: {port.product}")
            logger.debug(f"Port VID:PID: {port.vid:04X}:{port.pid:04X}")
            
            # Only accept Qualcomm modems
            if not ("Qualcomm HS-USB" in port.description and port.vid == 0x05C6):
                logger.debug(f"Port {port.device} is not a Qualcomm modem")
                return False
            
            # Skip diagnostic ports
            if self._is_diagnostic_port(port):
                logger.debug(f"Port {port.device} is a diagnostic port")
                return False
            
            # Must be a Franklin T9 modem port
            if "Android Modem" not in port.description:
                logger.debug(f"Port {port.device} is not an Android Modem port")
                return False
                
            logger.info(f"Found Franklin T9 modem on port {port.device}")
            return True
                
        except Exception as e:
            logger.error(f"Error checking modem type: {e}")
            return False

    def _validate_phone_number(self, number: str) -> bool:
        """Validate phone number format."""
        if not number:
            return False
            
        # Remove common phone number formatting including + prefix
        clean_number = re.sub(r'[\s\-\(\)\+]', '', number)
        
        # Check if it's exactly 11 digits (country code + number)
        is_valid = clean_number.isdigit() and len(clean_number) == 11
        logger.debug(f"Phone number validation: {number} -> {clean_number} -> {is_valid}")
        return clean_number if is_valid else None  # Return cleaned number if valid

    def _check_modem_status(self, port) -> str:
        """Check if modem is actually ready by testing AT commands."""
        try:
            with serial.Serial(port, baudrate=115200, timeout=1) as modem:
                # Test basic AT command
                modem.write(b'AT\r\n')
                time.sleep(0.1)
                response = modem.read_all().decode('utf-8', errors='ignore')
                
                if 'OK' not in response:
                    return 'error'
                    
                # Test if modem is registered on network
                modem.write(b'AT+CREG?\r\n')
                time.sleep(0.1)
                response = modem.read_all().decode('utf-8', errors='ignore')
                
                if '+CREG: 0,1' in response or '+CREG: 0,5' in response:
                    return 'ready'
                else:
                    return 'not_registered'
                
        except Exception as e:
            logger.error(f"Error checking modem status: {e}")
            return 'error'

    def _add_modem(self, port):
        """Initialize and add a new modem."""
        try:
            logger.debug(f"Attempting to add modem on port {port.device}")
            modem = serial.Serial(port.device, baudrate=115200, timeout=1)
            
            # Initialize modem
            commands = [
                ('AT', 0.1),  # Basic AT command
                ('ATE0', 0.1),  # Turn off echo
                ('AT+CMEE=2', 0.1),  # Extended error reporting
                ('AT+CIMI', 0.1),  # Get IMSI
                ('AT+CCID', 0.1),  # Get ICCID
                ('AT+CREG?', 0.1),  # Get Network Registration Status
                ('AT+CNUM', 0.1),  # Get phone number
                ('AT+COPS?', 0.1),  # Get carrier
            ]
            
            responses = {}
            for cmd, delay in commands:
                modem.write(f"{cmd}\r\n".encode())
                time.sleep(delay)
                response = modem.read_all().decode('utf-8', errors='ignore')
                responses[cmd] = response
                logger.debug(f"Command {cmd} response: {response}")
            
            # Parse responses
            imsi = self._parse_at_response(responses['AT+CIMI'], '+CIMI')
            iccid = self._parse_at_response(responses['AT+CCID'], '+CCID')
            phone = self._parse_at_response(responses['AT+CNUM'], '+CNUM')
            carrier = self._parse_at_response(responses['AT+COPS?'], '+COPS')
            
            logger.debug(f"Parsed responses - IMSI: {imsi}, ICCID: {iccid}, Phone: {phone}, Carrier: {carrier}")

            # Only add modem if we got a valid phone number or it's a Franklin T9
            is_franklin = "Qualcomm HS-USB" in port.description and not self._is_diagnostic_port(port)
            validated_phone = self._validate_phone_number(phone)
            
            if validated_phone or is_franklin:
                modem_info = {
                    'port': port.device,
                    'imsi': imsi or 'Unknown',
                    'iccid': iccid or 'Unknown',                    
                    'phone': validated_phone or 'Unknown',
                    'status': 'active',  # Set status to active since modem is connected
                    'last_seen': time.time(),
                    'manufacturer': port.manufacturer or 'Unknown',
                    'product': port.product or port.description or 'Unknown',
                    'vid': f"{port.vid:04X}" if port.vid else 'Unknown',
                    'pid': f"{port.pid:04X}" if port.pid else 'Unknown',
                    'carrier': carrier or 'Unknown',
                    'type': 'Franklin T9' if is_franklin else 'Generic GSM',
                    'operator': 'physic'  # Always set operator to physic
                }
                
                self.modems[port.device] = modem_info
                self.connected_modems.add(port.device)  # Mark as connected
                
                # Register with server if available
                if self.server:
                    self.server.register_modem(validated_phone or port.device, modem_info)
                    logger.info(f"Registered modem {validated_phone or port.device} with server")
                
                logger.info(f"Added modem: {modem_info}")
            else:
                logger.debug(f"Skipping port {port.device}: No valid phone number and not a Franklin T9 modem")

            modem.close()
            
        except Exception as e:
            logger.error(f"Error adding modem on port {port.device}: {e}")

    def _remove_modem(self, port):
        """Remove a disconnected modem."""
        if port in self.modems:
            logger.info(f"Removed modem: {self.modems[port]}")
            self.modems.pop(port)

    def _parse_at_response(self, response: str, command: str) -> Optional[str]:
        """Parse AT command response to extract relevant information."""
        if not response:
            return None
            
        lines = response.split('\r\n')
        for line in lines:
            if command in line:
                # Extract the value after the command
                parts = line.split(':')
                if len(parts) > 1:
                    value = parts[1].strip()
                    # Handle CNUM response format
                    if command == '+CNUM' and ',' in value:
                        number_parts = value.split(',')
                        if len(number_parts) >= 2:
                            # Remove + prefix if present
                            number = number_parts[1].strip('"').lstrip('+')
                            return number
                    # Handle COPS response format
                    elif command == '+COPS' and ',' in value:
                        cops_parts = value.split(',')
                        if len(cops_parts) >= 3:
                            return cops_parts[2].strip('"')
                    return value
                
            # Handle case where response is just the value
            elif line.strip() and not any(x in line for x in ['OK', 'ERROR']):
                return line.strip()
        return None

    def get_active_modems(self) -> List[Dict]:
        """Get list of active modems."""
        return list(self.modems.values())

    def get_modem_by_phone(self, phone: str) -> Optional[Dict]:
        """Get modem info by phone number."""
        for modem in self.modems.values():
            if modem['phone'] == phone:
                return modem
        return None

    def register_modem_with_server(self, modem_info: dict):
        """Register modem with the server."""
        try:
            if not self.server:
                logger.warning("No server reference available for modem registration")
                return
            
            # Use phone number as key, or port if phone number is unknown
            key = modem_info.get('phone', modem_info['port'])
            if key == 'Unknown':
                key = modem_info['port']
            
            # Create a copy of modem info to avoid modifying the original
            registration_info = modem_info.copy()
            registration_info['status'] = 'ready'
            registration_info['last_seen'] = time.time()
            
            # Register with server
            self.server.register_modem(key, registration_info)
            logger.info(f"Successfully registered modem {key} with server")
            
        except Exception as e:
            logger.error(f"Error registering modem: {e}")

    def get_all_device_info(self) -> List[Dict]:
        """Get information about all connected devices."""
        devices = []
        for port, info in self.modems.items():
            device_info = {
                'device_name': info.get('product', 'Unknown'),
                'com_port': port,
                'imei': info.get('imsi', 'Unknown'),
                'iccid': info.get('iccid', 'Unknown'),
                'phone_number': info.get('phone', 'Unknown'),
                'carrier': info.get('carrier', 'Unknown'),
                'status': 'Connected' if port in self.connected_modems else 'Disconnected'
            }
            devices.append(device_info)
        return devices

    def check_sms(self, port: str) -> List[Dict]:
        """Check for SMS messages on a specific modem."""
        try:
            if port not in self.modems:
                logger.error(f"Port {port} not found in modems")
                return []

            modem = serial.Serial(port, baudrate=115200, timeout=1)
            messages = []

            # Set text mode
            modem.write(b'AT+CMGF=1\r\n')
            time.sleep(0.1)
            modem.read_all()  # Clear buffer

            # List all messages
            modem.write(b'AT+CMGL="ALL"\r\n')
            time.sleep(0.5)
            response = modem.read_all().decode('utf-8', errors='ignore')

            # Parse messages
            msg_lines = response.split('\r\n')
            current_msg = None

            for line in msg_lines:
                if line.startswith('+CMGL:'):
                    if current_msg:
                        messages.append(current_msg)
                    # Parse message header
                    parts = line.split(',')
                    if len(parts) >= 4:
                        current_msg = {
                            'index': parts[0].split(':')[1].strip(),
                            'status': parts[1].strip('"'),
                            'sender': parts[2].strip('"'),
                            'timestamp': parts[4].strip('"') if len(parts) > 4 else '',
                            'text': ''
                        }
                elif line.strip() and current_msg:
                    current_msg['text'] = line.strip()

            if current_msg:
                messages.append(current_msg)

            modem.close()
            return messages

        except Exception as e:
            logger.error(f"Error checking SMS on port {port}: {e}")
            return []

    def send_at_command(self, port: str, command: str) -> str:
        """Send AT command to modem and return response."""
        try:
            if port not in self.modems:
                return "Error: Port not found"

            modem = serial.Serial(port, baudrate=115200, timeout=1)
            
            # Add AT prefix if not present
            if not command.upper().startswith('AT'):
                command = 'AT' + command

            # Send command
            modem.write(f"{command}\r\n".encode())
            time.sleep(0.5)
            response = modem.read_all().decode('utf-8', errors='ignore')
            
            modem.close()
            return response.strip()

        except Exception as e:
            logger.error(f"Error sending AT command to port {port}: {e}")
            return f"Error: {str(e)}"

    def find_franklin_t9_devices(self) -> List[str]:
        """Find Franklin T9 modems."""
        new_ports = []
        for port in serial.tools.list_ports.comports():
            if "Qualcomm HS-USB" in port.description and not self._is_diagnostic_port(port):
                if port.device not in self.modems:
                    new_ports.append(port.device)
        return new_ports

    def connect_all(self):
        """Connect to all modems."""
        for port in self.modems:
            try:
                modem = serial.Serial(port, baudrate=115200, timeout=1)
                modem.close()
                self.connected_modems.add(port)
                logger.info(f"Connected to modem on port {port}")
            except Exception as e:
                logger.error(f"Failed to connect to modem on port {port}: {e}")

    def disconnect_all(self):
        """Disconnect from all modems."""
        self.connected_modems.clear()
        logger.info("Disconnected from all modems")

    def _get_imei(self, port) -> str:
        """Get IMEI from modem."""
        try:
            with serial.Serial(port.device, baudrate=115200, timeout=1) as modem:
                modem.write(b'AT+CGSN\r\n')
                time.sleep(0.1)
                response = modem.read_all().decode('utf-8', errors='ignore')
                # Extract IMEI from response
                match = re.search(r'\d{15}', response)
                return match.group(0) if match else 'N/A'
        except Exception as e:
            logger.error(f"Error getting IMEI: {e}")
            return 'N/A'

    def _get_phone_number(self, port) -> str:
        """Get phone number from modem."""
        try:
            with serial.Serial(port.device, baudrate=115200, timeout=1) as modem:
                modem.write(b'AT+CNUM\r\n')
                time.sleep(0.1)
                response = modem.read_all().decode('utf-8', errors='ignore')
                # Extract phone number from response
                match = re.search(r'\+1(\d{10})', response)
                return match.group(1) if match else 'N/A'
        except Exception as e:
            logger.error(f"Error getting phone number: {e}")
            return 'N/A'

    def _get_signal_strength(self, port) -> str:
        """Get signal strength from modem."""
        try:
            with serial.Serial(port.device, baudrate=115200, timeout=1) as modem:
                modem.write(b'AT+CSQ\r\n')
                time.sleep(0.1)
                response = modem.read_all().decode('utf-8', errors='ignore')
                # Extract signal strength from response
                match = re.search(r'\+CSQ:\s*(\d+),', response)
                if match:
                    csq = int(match.group(1))
                    if csq == 99:
                        return 'No Signal'
                    # Convert CSQ to percentage (0-31 scale)
                    percentage = min(100, int((csq / 31) * 100))
                    return f"{percentage}%"
                return 'N/A'
        except Exception as e:
            logger.error(f"Error getting signal strength: {e}")
            return 'N/A'