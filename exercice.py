import pandas as pd
import time
import logging
import re
import io
import fitz  # PyMuPDF for PDF processing
import pytesseract  # For OCR on images
from PIL import Image
import msal
import requests
from datetime import datetime, timedelta
import json
import base64
from typing import List, Dict, Optional, Tuple
import os
from pathlib import Path
from dotenv import load_dotenv


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('email_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class EmailMonitorSystem:
    def __init__(self):
        """
        Initialize the email monitoring system
        """

        #Initialize env vars
        load_dotenv()

        print(os.getenv('SCOPE'))
        
        # Configuration dictionary - Update with your credentials
        self.config = {
            "client_id": os.getenv('CLIENT_ID'),  # No client_secret needed for device flow
            "tenant_id": os.getenv('TENANT_ID'),  # Use 'common' for personal accounts
            "authority": os.getenv('AUTHORITY'),
            "scope": os.environ.get('SCOPE').split(' '),
            "monitor_email": os.getenv('MONITOR_EMAIL'),
            "alert_email": os.getenv('ALERT_EMAIL'),
            "blacklist_file": os.getenv('BLACKLIST_FILE'),
            "check_interval": os.getenv('CHECK_INTERVAL'),
            "tesseract_path": os.getenv('TESSERACT_PATH')  # Update this path as needed
        }
        
        self.app = None
        self.access_token = None
        self.blacklist_df = None
        self.processed_emails = set()
        self.last_check_time = datetime.now()
        
        # Initialize MSAL application
        self.init_msal_app()
        
        # Load blacklist
        self.load_blacklist()

        
    
    def init_msal_app(self):
        """Initialize MSAL application for authentication"""
        self.app = msal.PublicClientApplication(
            self.config["client_id"],
            authority=self.config["authority"]
        )
    
    def get_access_token(self) -> str:
        """Get access token using device code flow"""
        # Try to get token from cache first
        accounts = self.app.get_accounts()
        if accounts:
            result = self.app.acquire_token_silent(
                self.config["scope"],
                account=accounts[0]
            )
            if result and "access_token" in result:
                self.access_token = result["access_token"]
                logger.info("Successfully acquired token from cache")
                return self.access_token
        
        # If no cached token, use device code flow
        logger.info("No cached token found, initiating device code flow...")
        
        flow = self.app.initiate_device_flow(scopes=self.config["scope"])
        
        if "user_code" not in flow:
            raise Exception("Failed to create device flow")
        
        # Display the device code to user
        print("\n" + "="*60)
        print("AUTHENTICATION REQUIRED")
        print("="*60)
        print(flow["message"])
        print("="*60)
        print("Please complete the authentication in your browser.")
        print("Waiting for authentication to complete...")
        print("="*60 + "\n")
        
        # Wait for user to authenticate
        result = self.app.acquire_token_by_device_flow(flow)
        
        if "access_token" in result:
            self.access_token = result["access_token"]
            logger.info("Successfully acquired access token via device flow")
            return self.access_token
        else:
            error_msg = result.get('error_description', result.get('error', 'Unknown error'))
            logger.error(f"Failed to acquire token: {error_msg}")
            logger.error(f"Full error response: {result}")
            raise Exception(f"Failed to acquire access token: {error_msg}")
    
    def load_blacklist(self):
        """Load blacklist CSV file"""
        try:
            self.blacklist_df = pd.read_csv(self.config["blacklist_file"])
            required_columns = ['first name', 'last name', 'cin', 'vehicule make', 'imm', 'color']
            
            # Check if all required columns exist
            missing_columns = [col for col in required_columns if col not in self.blacklist_df.columns]
            if missing_columns:
                logger.error(f"Missing columns in blacklist: {missing_columns}")
                raise ValueError(f"Blacklist file missing required columns: {missing_columns}")
            
            # Convert to lowercase for case-insensitive matching
            self.blacklist_df['first name'] = self.blacklist_df['first name'].astype(str).str.lower().str.strip()
            self.blacklist_df['last name'] = self.blacklist_df['last name'].astype(str).str.lower().str.strip()
            self.blacklist_df['cin'] = self.blacklist_df['cin'].astype(str).str.strip()
            self.blacklist_df['imm'] = self.blacklist_df['imm'].astype(str).str.strip()
            
            logger.info(f"Loaded blacklist with {len(self.blacklist_df)} entries")
            
        except Exception as e:
            logger.error(f"Error loading blacklist: {str(e)}")
            raise
    
    def test_authentication(self):
        """Test authentication and permissions"""
        try:
            if not self.access_token:
                self.get_access_token()
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            
            # Test basic Graph API access
            test_url = "https://graph.microsoft.com/v1.0/me"
            response = requests.get(test_url, headers=headers)
            
            if response.status_code == 200:
                logger.info("Successfully authenticated with Graph API")
                logger.info(f"Authenticated as: {response.json().get('displayName', 'Unknown')}")
            else:
                logger.error(f"Authentication test failed: {response.status_code} - {response.text}")
            
            # Test access to user's mailbox
            mailbox_url = f"https://graph.microsoft.com/v1.0/me/messages"
            params = {'$top': 1}
            
            response = requests.get(mailbox_url, headers=headers, params=params)
            
            if response.status_code == 200:
                logger.info(f"Successfully accessed mailbox for authenticated user")
                return True
            else:
                logger.error(f"Failed to access mailbox: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Authentication test failed: {str(e)}")
            return False
    
    def get_new_emails(self) -> List[Dict]:
        """Get new emails from the monitored account"""
        if not self.access_token:
            self.get_access_token()
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        
        # Format datetime for OData filter
        filter_time = self.last_check_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        
        # Get emails from the authenticated user's mailbox
        url = f"https://graph.microsoft.com/v1.0/me/messages"
        params = {
            '$filter': f"receivedDateTime gt {filter_time}",
            '$expand': 'attachments',
            '$orderby': 'receivedDateTime desc'
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            emails = response.json().get('value', [])
            logger.info(f"Found {len(emails)} new emails")
            
            return emails
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching emails: {str(e)}")
            return []
    
    def download_attachment(self, email_id: str, attachment_id: str) -> Optional[bytes]:
        """Download attachment content"""
        if not self.access_token:
            self.get_access_token()
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        
        url = f"https://graph.microsoft.com/v1.0/me/messages/{email_id}/attachments/{attachment_id}"
        
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            
            attachment_data = response.json()
            content_bytes = base64.b64decode(attachment_data['contentBytes'])
            
            return content_bytes
            
        except Exception as e:
            logger.error(f"Error downloading attachment: {str(e)}")
            return None
    
    def extract_text_from_pdf(self, pdf_content: bytes) -> str:
        """Extract text from PDF using PyMuPDF"""
        try:
            doc = fitz.open(stream=pdf_content, filetype="pdf")
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {str(e)}")
            return ""
    
    def extract_text_from_image(self, image_content: bytes) -> str:
        """Extract text from image using OCR"""
        try:
            # Set tesseract path if configured
            if self.config.get("tesseract_path"):
                pytesseract.pytesseract.tesseract_cmd = self.config["tesseract_path"]
            
            image = Image.open(io.BytesIO(image_content))
            text = pytesseract.image_to_string(image)
            return text
        except Exception as e:
            logger.error(f"Error extracting text from image: {str(e)}")
            return ""
    
    def extract_text_from_excel(self, excel_content: bytes) -> str:
        """Extract text from Excel file"""
        try:
            df = pd.read_excel(io.BytesIO(excel_content), sheet_name=None)
            text = ""
            for sheet_name, sheet_df in df.items():
                text += f"Sheet: {sheet_name}\n"
                text += sheet_df.to_string(index=False) + "\n\n"
            return text
        except Exception as e:
            logger.error(f"Error extracting text from Excel: {str(e)}")
            return ""
    
    def extract_text_from_csv(self, csv_content: bytes) -> str:
        """Extract text from CSV file"""
        try:
            df = pd.read_csv(io.BytesIO(csv_content))
            return df.to_string(index=False)
        except Exception as e:
            logger.error(f"Error extracting text from CSV: {str(e)}")
            return ""
    
    def extract_text_from_attachment(self, attachment_content: bytes, filename: str) -> str:
        """Extract text from attachment based on file type"""
        filename_lower = filename.lower()
        
        if filename_lower.endswith('.pdf'):
            return self.extract_text_from_pdf(attachment_content)
        elif filename_lower.endswith(('.xlsx', '.xls')):
            return self.extract_text_from_excel(attachment_content)
        elif filename_lower.endswith('.csv'):
            return self.extract_text_from_csv(attachment_content)
        elif filename_lower.endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp')):
            return self.extract_text_from_image(attachment_content)
        else:
            logger.warning(f"Unsupported file type: {filename}")
            return ""
    
    def check_blacklist_matches(self, text: str) -> List[Tuple[pd.Series, str, str]]:
        """Check text against blacklist and return matches"""
        matches = []
        text_lower = text.lower()
        
        for index, row in self.blacklist_df.iterrows():
            # Check CIN match
            cin = str(row['cin']).strip()
            if cin and cin in text:
                matches.append((row, 'cin', cin))
                logger.info(f"CIN match found: {cin}")
            
            # Check IMM match
            imm = str(row['imm']).strip()
            if imm and imm in text:
                matches.append((row, 'imm', imm))
                logger.info(f"IMM match found: {imm}")
            
            # Check first name + last name combination
            first_name = str(row['first name']).strip()
            last_name = str(row['last name']).strip()
            
            if first_name and last_name:
                # Check for exact full name match
                full_name = f"{first_name} {last_name}"
                if full_name in text_lower:
                    matches.append((row, 'full_name', full_name))
                    logger.info(f"Full name match found: {full_name}")
                
                # Check for reverse order
                full_name_reverse = f"{last_name} {first_name}"
                if full_name_reverse in text_lower:
                    matches.append((row, 'full_name', full_name_reverse))
                    logger.info(f"Full name (reverse) match found: {full_name_reverse}")
        
        return matches
    
    def send_alert_email(self, matches: List[Tuple[pd.Series, str, str]], email_subject: str, attachment_name: str):
        """Send alert email with match details"""
        if not self.access_token:
            self.get_access_token()
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        
        # Build email body
        body_lines = [
            f"SECURITY ALERT: Blacklist match found in email",
            f"Original email subject: {email_subject}",
            f"Attachment: {attachment_name}",
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "MATCHES FOUND:",
            "=" * 50
        ]
        
        for match_row, match_type, match_value in matches:
            body_lines.extend([
                f"Match Type: {match_type}",
                f"Match Value: {match_value}",
                f"Blacklist Entry:",
                f"  - First Name: {match_row['first name']}",
                f"  - Last Name: {match_row['last name']}",
                f"  - CIN: {match_row['cin']}",
                f"  - Vehicle Make: {match_row['vehicule make']}",
                f"  - IMM: {match_row['imm']}",
                f"  - Color: {match_row['color']}",
                "-" * 30
            ])
        
        email_body = "\n".join(body_lines)
        
        # Prepare email message
        message = {
            "message": {
                "subject": f"SECURITY ALERT: Blacklist Match Detected",
                "body": {
                    "contentType": "Text",
                    "content": email_body
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": self.config["alert_email"]
                        }
                    }
                ]
            }
        }
        
        url = f"https://graph.microsoft.com/v1.0/me/sendMail"
        
        try:
            response = requests.post(url, headers=headers, json=message)
            response.raise_for_status()
            logger.info(f"Alert email sent successfully to {self.config['alert_email']}")
        except Exception as e:
            logger.error(f"Error sending alert email: {str(e)}")
    
    def process_email(self, email: Dict):
        """Process a single email and check attachments"""
        email_id = email['id']
        subject = email.get('subject', 'No Subject')
        
        logger.info(f"Processing email: {subject}")
        
        # Skip if already processed
        if email_id in self.processed_emails:
            return
        
        self.processed_emails.add(email_id)
        
        # Check if email has attachments
        attachments = email.get('attachments', [])
        if not attachments:
            logger.info("No attachments found in email")
            return
        
        # Process each attachment
        for attachment in attachments:
            attachment_id = attachment['id']
            filename = attachment['name']
            
            # Check if attachment is a supported file type
            supported_extensions = ['.pdf', '.xlsx', '.xls', '.csv', '.png', '.jpg', '.jpeg', '.tiff', '.bmp']
            if not any(filename.lower().endswith(ext) for ext in supported_extensions):
                logger.info(f"Skipping unsupported attachment: {filename}")
                continue
            
            logger.info(f"Processing attachment: {filename}")
            
            # Download attachment
            attachment_content = self.download_attachment(email_id, attachment_id)
            if not attachment_content:
                continue
            
            # Extract text from attachment
            text = self.extract_text_from_attachment(attachment_content, filename)
            if not text:
                continue
            
            # Check for blacklist matches
            matches = self.check_blacklist_matches(text)
            
            # Send alert if matches found
            if matches:
                logger.warning(f"Blacklist matches found in {filename}")
                self.send_alert_email(matches, subject, filename)
    
    def run_monitoring_loop(self):
        """Main monitoring loop"""
        logger.info("Starting email monitoring system...")
        
        # Test authentication first
        if not self.test_authentication():
            logger.error("Authentication failed. Please check your credentials and permissions.")
            return
        
        while True:
            try:
                # Get new emails
                new_emails = self.get_new_emails()
                
                # Process each new email
                for email in new_emails:
                    self.process_email(email)
                
                # Update last check time
                self.last_check_time = datetime.now()
                
                # Wait before next check
                time.sleep(self.config.get("check_interval", 60))
                
            except KeyboardInterrupt:
                logger.info("Monitoring stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {str(e)}")
                time.sleep(30)  # Wait before retrying

def main():
    """Main function to run the email monitoring system"""
    try:
        monitor = EmailMonitorSystem()
        monitor.run_monitoring_loop()
    except Exception as e:
        logger.error(f"Failed to start monitoring system: {str(e)}")

if __name__ == "__main__":
    main()