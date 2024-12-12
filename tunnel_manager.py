import subprocess
import json
import os
import logging
import time
from typing import Optional
from config import config

logger = logging.getLogger(__name__)

class TunnelManager:
    def __init__(self, port: int = 5000, auth_token: Optional[str] = None):
        self.port = port
        self.auth_token = auth_token
        self.process = None
        self.url = None
        
        # Get path from config
        self.localtonet_path = config.get('localtonet_path')
        
        if not self.localtonet_path or not os.path.exists(self.localtonet_path):
            logger.error(f"LocalToNet not found at configured path: {self.localtonet_path}")
        
    def _kill_existing_localtonet(self):
        """Kill any existing LocalToNet processes."""
        try:
            if os.name == 'nt':  # Windows
                # Find and kill localtonet processes
                cmd = ['taskkill', '/F', '/IM', 'localtonet.exe']
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                logger.info("Killed existing LocalToNet processes")
            else:  # Linux/Mac
                cmd = ['pkill', 'localtonet']
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Wait a moment for processes to clean up
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Error killing existing LocalToNet processes: {e}")

    def start(self) -> Optional[str]:
        """Start the tunnel and return the public URL."""
        try:
            # Kill any existing LocalToNet processes first
            self._kill_existing_localtonet()

            # Check if executable exists
            if not os.path.exists(self.localtonet_path):
                logger.error("LocalToNet executable not found")
                return None

            # Check auth token
            if not self.auth_token:
                logger.error("No LocalToNet auth token provided")
                return None

            # Build localtonet command
            cmd = [
                self.localtonet_path,
                '--authtoken', self.auth_token,
                '--protocol', 'http',
                '--port', str(self.port)
            ]
            
            logger.info(f"Starting LocalToNet tunnel with command: {' '.join(cmd)}")
            
            # Start localtonet process from its directory
            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    bufsize=1,
                    cwd=os.path.dirname(self.localtonet_path)
                )
            except Exception as e:
                logger.error(f"Failed to start LocalToNet process: {str(e)}")
                return None

            # Wait for tunnel to establish
            start_time = time.time()
            timeout = 30  # 30 seconds timeout
            
            logger.info("Waiting for tunnel to establish...")
            
            while time.time() - start_time < timeout:
                if self.process.poll() is not None:
                    stdout, stderr = self.process.communicate()
                    logger.error(f"LocalToNet process ended unexpectedly")
                    logger.error(f"stdout: {stdout}")
                    logger.error(f"stderr: {stderr}")
                    return None
                    
                # Read output line by line
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        break
                        
                    logger.info(f"LocalToNet output: {line.strip()}")
                    # Look for URL in different formats
                    if "tunnel url:" in line.lower() or "tunnel created:" in line.lower():
                        # Extract URL more reliably
                        parts = line.split()
                        for part in parts:
                            if part.startswith('http'):
                                self.url = part.strip()
                                # Make URL very visible in logs
                                logger.info("=" * 60)
                                logger.info("SERVER URL FOUND:")
                                logger.info(self.url)
                                logger.info("Use this URL to access your endpoints")
                                logger.info("=" * 60)
                                return self.url
                    elif "error" in line.lower():
                        logger.error(f"LocalToNet error: {line.strip()}")
                        self.stop()
                        return None
                        
                time.sleep(0.1)
            
            # Timeout reached
            logger.error("Timeout waiting for LocalToNet tunnel to start")
            self.stop()
            return None
                
        except Exception as e:
            logger.error(f"Error starting LocalToNet tunnel: {str(e)}")
            if self.process:
                stdout, stderr = self.process.communicate()
                logger.error(f"Process output: {stdout}")
                logger.error(f"Process errors: {stderr}")
            self.stop()
            return None
            
    def stop(self):
        """Stop the tunnel."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
            self.url = None
            logger.info("LocalToNet tunnel stopped")
            
    def get_public_url(self) -> Optional[str]:
        """Get the current public URL."""
        return self.url