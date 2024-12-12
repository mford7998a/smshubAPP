import logging
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional
from flask import Request, Response

class APILogger:
    def __init__(self, log_dir: str = 'logs/api'):
        self.log_dir = log_dir
        
        # Ensure log directory exists
        os.makedirs(log_dir, exist_ok=True)
        
        # Set up logging
        self.logger = logging.getLogger(__name__)
        
        # Create a new log file for each day
        self.current_date = datetime.now().strftime('%Y-%m-%d')
        self.log_file = os.path.join(log_dir, f'api_requests_{self.current_date}.log')
        
        # Set up file handler
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        )
        self.logger.addHandler(file_handler)
        self.logger.setLevel(logging.INFO)

    def _rotate_log_file_if_needed(self):
        """Check and rotate log file if date has changed."""
        current_date = datetime.now().strftime('%Y-%m-%d')
        if current_date != self.current_date:
            self.current_date = current_date
            self.log_file = os.path.join(self.log_dir, f'api_requests_{self.current_date}.log')
            
            # Update file handler
            for handler in self.logger.handlers[:]:
                if isinstance(handler, logging.FileHandler):
                    self.logger.removeHandler(handler)
            
            new_handler = logging.FileHandler(self.log_file)
            new_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            self.logger.addHandler(new_handler)

    def _sanitize_headers(self, headers: Dict) -> Dict:
        """Remove sensitive information from headers."""
        sanitized = dict(headers)
        sensitive_keys = ['authorization', 'cookie', 'api-key']
        
        for key in sensitive_keys:
            if key.lower() in sanitized:
                sanitized[key.lower()] = '[REDACTED]'
        
        return sanitized

    def log_request(self, request: Request, include_headers: bool = True) -> Dict[str, Any]:
        """Log incoming API request details."""
        self._rotate_log_file_if_needed()
        
        try:
            # Extract request data
            request_data = {
                'timestamp': datetime.now().isoformat(),
                'method': request.method,
                'url': request.url,
                'remote_addr': request.remote_addr,
                'path': request.path,
            }
            
            if include_headers:
                request_data['headers'] = self._sanitize_headers(dict(request.headers))
            
            # Try to get JSON body if present
            try:
                if request.is_json:
                    request_data['body'] = request.get_json()
                elif request.form:
                    request_data['body'] = dict(request.form)
                elif request.data:
                    request_data['body'] = request.data.decode('utf-8')
            except Exception as e:
                request_data['body'] = f'[Error parsing body: {str(e)}]'
            
            # Log the request
            self.logger.info(f"Incoming Request: {json.dumps(request_data, indent=2)}")
            return request_data
            
        except Exception as e:
            self.logger.error(f"Error logging request: {str(e)}")
            return {'error': str(e)}

    def log_response(self, response: Response, request_data: Optional[Dict] = None) -> None:
        """Log API response details."""
        self._rotate_log_file_if_needed()
        
        try:
            # Extract response data
            response_data = {
                'timestamp': datetime.now().isoformat(),
                'status_code': response.status_code,
                'headers': self._sanitize_headers(dict(response.headers)),
            }
            
            # Try to get response body
            try:
                if response.is_json:
                    response_data['body'] = response.get_json()
                else:
                    response_data['body'] = response.get_data(as_text=True)
            except Exception as e:
                response_data['body'] = f'[Error parsing body: {str(e)}]'
            
            # Include original request data if available
            if request_data:
                response_data['request'] = request_data
            
            # Log the response
            self.logger.info(f"API Response: {json.dumps(response_data, indent=2)}")
            
        except Exception as e:
            self.logger.error(f"Error logging response: {str(e)}")

    def get_logs(self, date: Optional[str] = None) -> list:
        """Retrieve logs for a specific date or current date."""
        if date is None:
            date = self.current_date
            
        log_file = os.path.join(self.log_dir, f'api_requests_{date}.log')
        
        if not os.path.exists(log_file):
            return []
            
        try:
            with open(log_file, 'r') as f:
                return [line.strip() for line in f if line.strip()]
        except Exception as e:
            self.logger.error(f"Error reading logs: {str(e)}")
            return [] 