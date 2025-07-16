# ---------------------------------------------------------
# This script tests the EmailService class from the resume_analyzer backend.
# It sends a test email to the sender's own email address to verify that the service is working correctly.
# Make sure to set the environment variables for email credentials in a .env file.
# ---------------------------------------------------------

import sys
import os
from dotenv import load_dotenv

# Add the project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Force reload the .env file
load_dotenv(override=True)

from resume_analyzer.backend.email_service import EmailService

def test_email_service():
    try:
        # Initialize email service
        email_service = EmailService()
        
        print("🔄 Testing EmailService class...")
        print(f"Sender Email: e1121724@u.nus.edu")
        print(f"Sender Name: {email_service.sender_name}")
        
        # Test basic email sending
        test_email = "e1121724@u.nus.edu"  # Send to yourself
        subject = "Test from EmailService Class"
        body = """This is a test email sent using the EmailService class.

If you receive this, the email service is working correctly!

Best regards,
Resume Management System"""
        
        # Send test email
        success = email_service.send_email(test_email, subject, body)
        
        if success:
            print("✅ EmailService is working correctly!")
        else:
            print("❌ EmailService failed to send email")
            
    except Exception as e:
        print(f"❌ Error testing EmailService: {e}")

if __name__ == "__main__":
    test_email_service()