import os
import sys
import subprocess
import logging
import requests
import tkinter as tk
from tkinter import ttk, messagebox
from config import config

logger = logging.getLogger(__name__)

class LocaltonetSetup:
    DOWNLOAD_URL = "https://localtonet.com/download/LocaltonetClient.zip"
    
    @staticmethod
    def is_installed() -> bool:
        """Check if localtonet is installed."""
        try:
            subprocess.run(['localtonet', '--version'], 
                         capture_output=True, 
                         check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    @staticmethod
    def download_and_install():
        """Download and install localtonet client."""
        try:
            # Create bin directory if it doesn't exist
            os.makedirs('bin', exist_ok=True)
            
            # Download the client
            logger.info("Downloading localtonet client...")
            response = requests.get(LocaltonetSetup.DOWNLOAD_URL)
            response.raise_for_status()
            
            # Save to zip file
            zip_path = os.path.join('bin', 'localtonet.zip')
            with open(zip_path, 'wb') as f:
                f.write(response.content)
            
            # Extract the zip
            import zipfile
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall('bin')
            
            # Add bin directory to PATH
            bin_path = os.path.abspath('bin')
            if bin_path not in os.environ['PATH']:
                os.environ['PATH'] = f"{bin_path}{os.pathsep}{os.environ['PATH']}"
            
            logger.info("Localtonet client installed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error installing localtonet: {e}")
            return False

    @staticmethod
    def show_token_dialog() -> str:
        """Show dialog to enter auth token."""
        root = tk.Tk()
        root.title("Localtonet Setup")
        root.geometry("600x400")
        
        # Center window
        root.eval('tk::PlaceWindow . center')
        
        frame = ttk.Frame(root, padding="20")
        frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Instructions
        instructions = """
1. Go to https://localtonet.com/ and create a free account
2. Download and install the Localtonet Client
3. Log in to your account on the website
4. Go to your Dashboard
5. Click on "API Access" in the left menu
6. Copy your API token and paste it below
        """
        
        ttk.Label(frame, text="Localtonet Setup", font=('Helvetica', 14, 'bold')).grid(row=0, column=0, pady=10)
        ttk.Label(frame, text=instructions, justify=tk.LEFT).grid(row=1, column=0, pady=10)
        
        # Token entry
        token_var = tk.StringVar()
        ttk.Label(frame, text="Enter your API token:").grid(row=2, column=0, pady=5)
        token_entry = ttk.Entry(frame, textvariable=token_var, width=50)
        token_entry.grid(row=3, column=0, pady=5)
        
        # Store token and close window
        def save_token():
            token = token_var.get().strip()
            if token:
                config.set("tunnel.auth_token", token)
                root.destroy()
            else:
                messagebox.showerror("Error", "Please enter your API token")
        
        # Open website button
        def open_website():
            import webbrowser
            webbrowser.open("https://localtonet.com/")
        
        ttk.Button(frame, text="Open Localtonet Website", command=open_website).grid(row=4, column=0, pady=10)
        ttk.Button(frame, text="Save Token", command=save_token).grid(row=5, column=0, pady=10)
        
        # Make window modal
        root.transient()
        root.grab_set()
        root.wait_window()
        
        return config.get("tunnel.auth_token")

def ensure_localtonet_setup() -> bool:
    """Ensure localtonet is installed and configured."""
    # Check if auth token exists
    auth_token = config.get("tunnel.auth_token")
    
    # If no token, show setup dialog
    if not auth_token:
        auth_token = LocaltonetSetup.show_token_dialog()
        if not auth_token:
            logger.error("No auth token provided")
            return False
    
    # Check if localtonet is installed
    if not LocaltonetSetup.is_installed():
        logger.info("Localtonet not found, installing...")
        if not LocaltonetSetup.download_and_install():
            logger.error("Failed to install localtonet")
            return False
    
    return True 