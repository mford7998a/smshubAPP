import requests
import json
import logging
import time

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_get_services():
    url = "https://fzn84ln.localto.net/"  # Note the trailing slash
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "SMSHubAgent/1.0",
        "Accept-Encoding": "gzip",
        "localtonet-skip-warning": "true"  # Added to bypass warning page
    }
    data = {
        "action": "GET_SERVICES",
        "key": "15431U1ea5e5b53572512438b03fbe8f96fa10"  # Exact key from screenshot
    }

    try:
        logger.info(f"Making request to {url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Data: {data}")
        
        response = requests.post(
            url,
            headers=headers,
            json=data,
            verify=False
        )
        
        logger.info(f"Response status code: {response.status_code}")
        logger.info(f"Response headers: {dict(response.headers)}")
        logger.info(f"Response content: {response.text}")
        
        return response.json()
    except Exception as e:
        logger.error(f"Error making request: {e}")
        return None

def test_get_number():
    """Test GET_NUMBER endpoint."""
    url = "https://fzn84ln.localto.net/"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "SMSHubAgent/1.0",
        "Accept-Encoding": "gzip",
        "localtonet-skip-warning": "true"
    }
    data = {
        "action": "GET_NUMBER",
        "key": "1543IU7eA5e5b5357251243Bb03fbe8f96fa10",
        "country": "russia",
        "operator": "any",
        "service": "vk",
        "sum": 10.00,  # Price in rubles
        "currency": 643,  # 643 is the code for RUB
        "exceptionPhoneSet": []  # Optional list of phone numbers to exclude
    }

    try:
        logger.info(f"\nTesting GET_NUMBER endpoint")
        logger.info(f"Making request to {url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Data: {data}")
        
        response = requests.post(
            url,
            headers=headers,
            json=data,
            verify=False
        )
        
        logger.info(f"Response status code: {response.status_code}")
        logger.info(f"Response headers: {dict(response.headers)}")
        logger.info(f"Response content: {response.text}")
        
        return response.json()
    except Exception as e:
        logger.error(f"Error making request: {e}")
        return None

def test_finish_activation(activation_id: int, status: int = 3):
    """Test FINISH_ACTIVATION endpoint.
    Status codes:
    1 - Do not provide for this service
    3 - Successfully sold
    4 - Cancelled
    5 - Refunded
    """
    url = "https://fzn84ln.localto.net/"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "SMSHubAgent/1.0",
        "Accept-Encoding": "gzip",
        "localtonet-skip-warning": "true"
    }
    data = {
        "action": "FINISH_ACTIVATION",
        "key": "1543IU7eA5e5b5357251243Bb03fbe8f96fa10",
        "activationId": activation_id,
        "status": status
    }

    try:
        logger.info(f"\nTesting FINISH_ACTIVATION endpoint")
        logger.info(f"Making request to {url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Data: {data}")
        
        response = requests.post(
            url,
            headers=headers,
            json=data,
            verify=False
        )
        
        logger.info(f"Response status code: {response.status_code}")
        logger.info(f"Response headers: {dict(response.headers)}")
        logger.info(f"Response content: {response.text}")
        
        return response.json()
    except Exception as e:
        logger.error(f"Error making request: {e}")
        return None

def test_push_sms(phone: str = None, text: str = None):
    """Test PUSH_SMS endpoint.
    This simulates receiving an SMS and forwarding it to SMSHub.
    """
    url = "https://fzn84ln.localto.net/"  # Local testing server
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "SMSHubAgent/1.0",
        "Accept-Encoding": "gzip",
        "localtonet-skip-warning": "true"
    }
    
    # If no phone provided, use the last one we got from GET_NUMBER
    if not phone:
        phone = "79281234567"  # Example number with country code
    
    # If no text provided, use a test message
    if not text:
        text = "VK: 123456 - your verification code"
        
    data = {
        "action": "PUSH_SMS",
        "key": "1543IU7eA5e5b5357251243Bb03fbe8f96fa10",  # Local testing key
        "smsId": int(time.time()),  # Use timestamp as SMS ID
        "phone": int(phone.replace("+", "").replace("-", "")),  # Clean number and convert to int
        "phoneFrom": "VK",  # Example sender name
        "text": text
    }

    try:
        logger.info(f"\nTesting PUSH_SMS endpoint")
        logger.info(f"Making request to {url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Data: {data}")
        
        response = requests.post(
            url,
            headers=headers,
            json=data,
            verify=False
        )
        
        logger.info(f"Response status code: {response.status_code}")
        logger.info(f"Response headers: {dict(response.headers)}")
        logger.info(f"Response content: {response.text}")
        
        return response.json()
    except Exception as e:
        logger.error(f"Error making request: {e}")
        return None

if __name__ == "__main__":
    # Test GET_SERVICES
    print("\n=== Testing GET_SERVICES ===")
    result = test_get_services()
    if result:
        print("\nGET_SERVICES Response:")
        print(json.dumps(result, indent=2))

    # Test GET_NUMBER
    print("\n=== Testing GET_NUMBER ===")
    result = test_get_number()
    phone_number = None
    if result:
        print("\nGET_NUMBER Response:")
        print(json.dumps(result, indent=2))
        phone_number = str(result.get('number'))
        
        # If we got a number, test finishing the activation
        activation_id = result.get('activationId')
        if activation_id:
            print("\n=== Testing FINISH_ACTIVATION ===")
            finish_result = test_finish_activation(activation_id)
            if finish_result:
                print("\nFINISH_ACTIVATION Response:")
                print(json.dumps(finish_result, indent=2))
    
    # Test PUSH_SMS using the number we got
    if phone_number:
        print("\n=== Testing PUSH_SMS ===")
        sms_result = test_push_sms(phone_number)
        if sms_result:
            print("\nPUSH_SMS Response:")
            print(json.dumps(sms_result, indent=2)) 