import logging
import time
from typing import Dict, Optional, List
from flask import Flask, request, jsonify
from config import config
from tunnel_manager import TunnelManager
from setup_localtonet import ensure_localtonet_setup
import threading
from datetime import datetime
from flask_cors import CORS
from flask_compress import Compress
import os
import json
from api_logger import APILogger

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SmsHubServer:
    def __init__(self, host='0.0.0.0', port=None):
        self.host = host
        self.port = port or config.get('server_port', 5000)
        self.app = Flask(__name__)
        self.api_logger = APILogger()  # Initialize our API logger
        
        # Enable CORS and compression
        CORS(self.app)
        Compress(self.app)
        
        # Configure SSL context if needed
        self.ssl_context = None
        if config.get('use_ssl', False):
            self.ssl_context = 'adhoc'
        
        # Initialize other components
        self.tunnel_manager = None
        self.services = {}
        self.modems = {}
        self.active_numbers = {}
        self.completed_activations = {}  # phone -> {service: completion_time}
        self.activation_log_file = "activation_history.txt"
        self.public_url = None
        self.smshub = None  # Will be set by main.py
        self.localtonet_url = "Waiting for connection..."  # Initialize with a default value
        
        # Initialize ModemManager
        from modem_manager import ModemManager
        self.modem_manager = ModemManager(self)
        self.modem_manager.start()  # Start scanning for modems
        
        # Load previous activation history
        self.load_activation_history()
        
        # Statistics tracking
        self.stats = {
            'total_earnings': 0.0,
            'today_earnings': 0.0,
            'total_activations': 0,
            'completed_activations': 0,
            'cancelled_activations': 0,
            'refunded_activations': 0,
            'service_stats': {},  # service -> {completed: 0, cancelled: 0, refunded: 0}
            'activation_times': [],  # List of activation durations for averaging
        }
        
        # Setup routes and start background tasks
        self.setup_routes()
        self.update_service_quantities()

    def setup_routes(self):
        """Setup Flask routes."""
        
        @self.app.before_request
        def log_request():
            """Log the incoming request."""
            return self.api_logger.log_request(request)

        @self.app.after_request
        def log_response(response):
            """Log the response."""
            # Get the request data that was stored by before_request
            request_data = getattr(request, '_logged_request', None)
            self.api_logger.log_response(response, request_data)
            return response

        @self.app.route('/', methods=['GET', 'POST'])
        @self.app.route('/smshub', methods=['GET', 'POST'])
        def handle_smshub_request():
            """Handle all SMS Hub requests."""
            try:
                logger.info("=== SMS Hub Request Received ===")
                logger.info(f"Method: {request.method}")
                logger.info(f"Headers: {dict(request.headers)}")
                logger.info(f"URL: {request.url}")
                
                # For GET requests, show status page
                if request.method == 'GET':
                    return jsonify({
                        'status': 'running',
                        'services': self.services,
                        'modems': len(self.modems),
                        'active_numbers': len(self.active_numbers)
                    })
                
                try:
                    data = request.json
                    logger.info(f"Request data: {data}")
                except Exception as e:
                    logger.error(f"Failed to parse JSON data: {e}")
                    return jsonify({'status': 'ERROR', 'error': 'Invalid JSON data'})
                
                if not data:
                    logger.error("No data provided in request")
                    return jsonify({'status': 'ERROR', 'error': 'No data provided'})

                key = data.get('key')
                action = data.get('action')
                logger.info(f"Key: {key}, Action: {action}")

                if not key or key != config.get('smshub_api_key'):
                    logger.error(f"Invalid API key: {key}")
                    return jsonify({'status': 'ERROR', 'error': 'Invalid API key'})

                # Handle different actions
                logger.debug(f"Handling action: {action}")
                if action == 'GET_SERVICES':
                    logger.debug("Processing GET_SERVICES")
                    return self.handle_get_services()
                elif action == 'GET_NUMBER':
                    logger.debug("Processing GET_NUMBER")
                    return self.handle_get_number(data)
                elif action == 'FINISH_ACTIVATION':
                    logger.debug("Processing FINISH_ACTIVATION")
                    return self.handle_finish_activation(data)
                elif action == 'PUSH_SMS':
                    logger.debug("Processing PUSH_SMS")
                    sms_content = data.get('sms_content', 'No content')
                    sender = data.get('sender', 'Unknown')
                    recipient = data.get('recipient', 'Unknown')
                    logger.info(f"SMS received: From={sender}, To={recipient}, Content={sms_content}")
                    return self.handle_push_sms(data)
                else:
                    logger.error(f"Unknown action: {action}")
                    return jsonify({'status': 'ERROR', 'error': 'Unknown action'})

            except Exception as e:
                logger.error(f"Error handling request: {e}", exc_info=True)
                return jsonify({'status': 'ERROR', 'error': str(e)})

        # Add CORS headers to all responses
        @self.app.after_request
        def after_request(response):
            response.headers.add('Access-Control-Allow-Origin', '*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,User-Agent,Accept-Encoding')
            response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE')
            return response

    def load_activation_history(self):
        """Load activation history from file."""
        try:
            if os.path.exists(self.activation_log_file):
                with open(self.activation_log_file, 'r') as f:
                    for line in f:
                        try:
                            data = json.loads(line.strip())
                            phone = data.get('phone')
                            service = data.get('service')
                            if phone and service:
                                if phone not in self.completed_activations:
                                    self.completed_activations[phone] = {}
                                self.completed_activations[phone][service] = data.get('timestamp')
                        except json.JSONDecodeError:
                            logger.error(f"Error parsing activation history line: {line}")
                logger.info(f"Loaded {len(self.completed_activations)} activation histories")
        except Exception as e:
            logger.error(f"Error loading activation history: {e}")

    def save_activation(self, phone: str, service: str, status: str):
        """Save activation to history file."""
        try:
            if status == 'completed':  # Only save completed activations
                timestamp = time.time()
                entry = {
                    'phone': phone,
                    'service': service,
                    'timestamp': timestamp,
                    'date': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
                }
                
                # Update in-memory record
                if phone not in self.completed_activations:
                    self.completed_activations[phone] = {}
                self.completed_activations[phone][service] = timestamp
                
                # Append to file
                with open(self.activation_log_file, 'a') as f:
                    f.write(json.dumps(entry) + '\n')
                    
                logger.info(f"Saved activation: {phone} - {service}")
        except Exception as e:
            logger.error(f"Error saving activation: {e}")

    def handle_get_services(self):
        """Handle GET_SERVICES request."""
        try:
            # Get list of currently active modems
            active_phones = [phone for phone, modem in self.modems.items() 
                           if modem.get('status') == 'active']
            total_active_phones = len(active_phones)
            
            # Count current active service usage
            active_services = {}
            for phone, activation in self.active_numbers.items():
                service = activation.get('service')
                if service and activation.get('status') == 'active':
                    active_services[service] = active_services.get(service, 0) + 1
            
            # Build response with services and their quantities
            services = {}
            
            # Only use services defined in config.json
            for service_id, enabled in config.get('services', {}).items():
                if enabled:
                    # For each service, count how many of our current active phones 
                    # have already completed this service
                    phones_used_for_service = sum(
                        1 for phone in active_phones
                        if (phone in self.completed_activations and 
                            service_id in self.completed_activations[phone])
                    )
                    
                    # Available = current active phones - phones already used for this service - currently active service count
                    available = max(0, total_active_phones - 
                               phones_used_for_service - 
                               active_services.get(service_id, 0))
                    
                    services[service_id] = available
            
            # Return response in correct format
            return jsonify({
                'status': 'SUCCESS',
                'services': services
            })
            
        except Exception as e:
            logger.error(f"Error handling GET_SERVICES request: {e}", exc_info=True)
            return jsonify({'status': 'ERROR', 'error': str(e)})

    def handle_get_number(self, data):
        """Handle GET_NUMBER request."""
        try:
            country = data.get('country')
            operator = data.get('operator')
            service = data.get('service')
            sum_amount = data.get('sum')
            currency = data.get('currency')
            exception_phones = data.get('exceptionPhoneSet', [])

            if not all([country, operator, service, sum_amount, currency]):
                return jsonify({'status': 'ERROR', 'error': 'Missing required fields'})

            # Check if service has available numbers
            service_quantity = 0
            for modem in self.modems.values():
                if modem.get('status') == 'active':
                    service_quantity += 1

            if service_quantity == 0:
                logger.info("No numbers available: No active modems found")
                return jsonify({'status': 'NO_NUMBERS'})

            # Find available modem
            for phone, modem in self.modems.items():
                if modem.get('status') != 'active':
                    continue

                # Check if phone is in exception list
                if any(phone.startswith(prefix) for prefix in exception_phones):
                    continue

                # Found a match (we don't check operator since all are 'physic')
                modem['status'] = 'busy'
                activation_id = int(time.time())  # Generate unique ID
                modem['activation_id'] = activation_id

                # Record activation
                self.active_numbers[phone] = {
                    'service': service,
                    'timestamp': time.time(),
                    'status': 'active',
                    'sum': sum_amount,
                    'activation_id': activation_id
                }
                logger.info(f"Activation started: ID={activation_id}, Phone={phone}, Service={service}, Sum={sum_amount}")
                
                # Update statistics
                self.stats['total_activations'] += 1

                return jsonify({
                    'status': 'SUCCESS',
                    'number': int(phone),  # Must be numeric
                    'activationId': activation_id
                })

            # No suitable numbers found
            logger.info("No numbers available: No suitable modems found")
            return jsonify({'status': 'NO_NUMBERS'})

        except Exception as e:
            logger.error(f"Error in get_number: {e}", exc_info=True)
            return jsonify({'status': 'ERROR', 'error': str(e)})

    def handle_finish_activation(self, data):
        """Handle FINISH_ACTIVATION request."""
        try:
            # Validate required fields
            activation_id = data.get('activationId')
            status = data.get('status')

            if not isinstance(activation_id, (int, float)) or not isinstance(status, (int, float)):
                return jsonify({'status': 'ERROR', 'error': 'Invalid field types'})

            # Find the activation by ID
            phone = None
            for p, modem in self.modems.items():
                if modem.get('activation_id') == activation_id:
                    phone = p
                    break

            if not phone:
                return jsonify({'status': 'ERROR', 'error': 'Activation not found'})

            activation = self.active_numbers.get(phone)
            if not activation:
                return jsonify({'status': 'ERROR', 'error': 'No active activation found'})

            # Update activation status
            if status == 3:  # Successfully sold
                self.save_activation(phone, activation['service'], 'completed')
                logger.info(f"Activation completed: {phone} - {activation['service']}")
                
            # Rest of the existing finish_activation logic...
            
            return jsonify({'status': 'SUCCESS'})

        except Exception as e:
            logger.error(f"Error in finish_activation: {e}", exc_info=True)
            return jsonify({'status': 'ERROR', 'error': str(e)})

    def register_modem(self, key: str, modem_info: dict):
        """Register a modem with the server."""
        try:
            logger.info(f"Registering modem with key: {key}")
            
            # Ensure operator is set to physic
            modem_info['operator'] = 'physic'
            modem_info['country'] = 'usaphysical'  # Also set the country
            
            self.modems[key] = modem_info
            self.update_service_quantities()  # Update available services
            logger.info(f"Successfully registered modem: {key} with status: {modem_info.get('status', 'unknown')}")
        except Exception as e:
            logger.error(f"Error registering modem: {e}")
            raise

    def unregister_modem(self, phone_number: str) -> None:
        """Unregister a modem."""
        self.modems.pop(phone_number, None)
        self.update_service_quantities()

    def update_service_quantities(self):
        """Update available service quantities based on active modems."""
        try:
            # Count all modems that are active and have operator set to 'physic'
            available_modems = sum(1 for modem in self.modems.values() 
                                 if modem.get('status') == 'active' 
                                 and modem.get('operator') == 'physic')
            
            logger.info(f"Found {available_modems} active modems with 'physic' operator")
            logger.debug(f"Current modems: {json.dumps(list(self.modems.values()), indent=2)}")
            
            # Update quantities for all enabled services
            for service, enabled in config.get('services', {}).items():
                if enabled:
                    self.services[service] = available_modems
                    logger.debug(f"Updated service {service} quantity to {available_modems}")
            
            logger.info(f"Updated service quantities: {self.services}")
            
        except Exception as e:
            logger.error(f"Error updating service quantities: {e}", exc_info=True)

    def get_services(self):
        """Get available services and their quantities."""
        return self.services

    def get_service_quantities(self) -> Dict[str, int]:
        """Get current quantities for all services."""
        try:
            # Update quantities first to ensure they're current
            self.update_service_quantities()
            return self.services
        except Exception as e:
            logger.error(f"Error getting service quantities: {e}")
            return {}

    def get_performance_metrics(self) -> Dict:
        """Get server performance metrics."""
        try:
            total_modems = len(self.modems)
            active_modems = sum(1 for modem in self.modems.values() 
                              if modem.get('status') == 'active')
            active_services = len(self.active_numbers)
            
            # Calculate success rate
            success_rate = 0
            if self.stats['total_activations'] > 0:
                success_rate = (self.stats['completed_activations'] / self.stats['total_activations']) * 100
            
            # Calculate average activation time
            avg_activation_time = 0
            if self.stats['activation_times']:
                avg_activation_time = sum(self.stats['activation_times']) / len(self.stats['activation_times'])
            
            return {
                'total_modems': total_modems,
                'active_modems': active_modems,
                'active_services': active_services,
                'success_rate': round(success_rate, 2),
                'avg_activation_time': round(avg_activation_time, 2),
                'total_activations': self.stats['total_activations'],
                'completed_activations': self.stats['completed_activations'],
                'cancelled_activations': self.stats['cancelled_activations'],
                'total_earnings': round(self.stats['total_earnings'], 2),
                'today_earnings': round(self.stats['today_earnings'], 2)
            }
        except Exception as e:
            logger.error(f"Error getting performance metrics: {e}")
            return {
                'total_modems': 0,
                'active_modems': 0,
                'active_services': 0,
                'success_rate': 0,
                'avg_activation_time': 0,
                'total_activations': 0,
                'completed_activations': 0,
                'cancelled_activations': 0,
                'total_earnings': 0,
                'today_earnings': 0
            }

    def get_public_url(self) -> Optional[str]:
        """Get the public URL for this server."""
        return self.public_url

    def run(self):
        """Run the server."""
        self.app.run(
            host=self.host, 
            port=self.port, 
            debug=False, 
            threaded=True,
            ssl_context=self.ssl_context
        )

    def stop(self):
        """Stop the server and cleanup."""
        if self.tunnel_manager:
            self.tunnel_manager.stop() 

    def handle_push_sms(self, data):
        """Handle PUSH_SMS request."""
        try:
            sms_id = data.get('smsId')
            phone = data.get('phone')
            phone_from = data.get('phoneFrom')
            text = data.get('text')

            if not all([sms_id, phone, phone_from, text]):
                return jsonify({'status': 'ERROR', 'error': 'Missing required fields'})

            # Validate types
            if not isinstance(sms_id, (int, float)):
                return jsonify({'status': 'ERROR', 'error': 'smsId must be numeric'})
            if not isinstance(phone, (int, float)):
                return jsonify({'status': 'ERROR', 'error': 'phone must be numeric'})
            if not isinstance(phone_from, str):
                return jsonify({'status': 'ERROR', 'error': 'phoneFrom must be string'})
            if not isinstance(text, str):
                return jsonify({'status': 'ERROR', 'error': 'text must be string'})

            # Log the SMS
            logger.info(f"Received SMS - ID: {sms_id}, From: {phone_from}, To: {phone}, Text: {text}")

            # Here you would typically store the SMS in your database
            # For now, we just return success
            return jsonify({'status': 'SUCCESS'})

        except Exception as e:
            logger.error(f"Error in push_sms: {e}", exc_info=True)
            return jsonify({'status': 'ERROR', 'error': str(e)})

    def get_statistics(self):
        """Get current statistics."""
        try:
            active_count = len(self.active_numbers)
            avg_time = 0
            if self.stats['activation_times']:
                avg_time = sum(self.stats['activation_times']) / len(self.stats['activation_times'])
            
            success_rate = 0
            if self.stats['total_activations'] > 0:
                success_rate = (self.stats['completed_activations'] / self.stats['total_activations']) * 100
            
            return {
                'total_earnings': self.stats['total_earnings'],
                'today_earnings': self.stats['today_earnings'],
                'total_activations': self.stats['total_activations'],
                'completed_activations': self.stats['completed_activations'],
                'cancelled_activations': self.stats['cancelled_activations'],
                'refunded_activations': self.stats['refunded_activations'],
                'active_count': active_count,
                'success_rate': success_rate,
                'average_time': avg_time,
                'service_stats': self.stats['service_stats']
            }
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {}
  