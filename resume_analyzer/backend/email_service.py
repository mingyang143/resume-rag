import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Optional
from dotenv import load_dotenv
from ..ingestion.helpers import connect_postgres, load_env_vars

load_dotenv()

class EmailService:
    def __init__(self):
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.sender_email = os.getenv("EMAIL_ADDRESS")  # Use EMAIL_ADDRESS from your .env
        self.sender_password = os.getenv("EMAIL_PASSWORD")  # Use EMAIL_PASSWORD from your .env
        self.sender_name = os.getenv("EMAIL_FROM_NAME", "HR Team")
        
        if not self.sender_email or not self.sender_password:
            raise ValueError("EMAIL_ADDRESS and EMAIL_PASSWORD must be set in environment variables")
    
    def get_email_template(self, template_name: str) -> Optional[Dict[str, str]]:
        """Fetch email template from database using your existing table structure."""
        try:
            env = load_env_vars()
            conn = connect_postgres(env)
            cur = conn.cursor()
            
            cur.execute("""
                SELECT subject_template, body_template 
                FROM public.email_templates 
                WHERE template_name = %s;
            """, (template_name,))
            
            result = cur.fetchone()
            cur.close()
            conn.close()
            
            if result:
                return {
                    'subject': result[0],
                    'body': result[1]
                }
            return None
            
        except Exception as e:
            print(f"Error fetching email template: {e}")
            return None
    
    def get_candidate_info(self, candidate_key: str) -> Optional[Dict]:
        """Fetch candidate information for email templating."""
        try:
            env = load_env_vars()
            conn = connect_postgres(env)
            cur = conn.cursor()
            
            cur.execute("""
                SELECT candidate_key, email, university, applied_position, 
                       salary, part_or_full, from_date, to_date
                FROM public.resumes_metadata 
                WHERE candidate_key = %s 
                LIMIT 1;
            """, (candidate_key,))
            
            result = cur.fetchone()
            cur.close()
            conn.close()
            
            if result:
                return {
                    'candidate_name': result[0],  # Using candidate_key as name
                    'email': result[1],
                    'university': result[2],
                    'position': result[3],  # Match your template variable
                    'applied_position': result[3],
                    'salary': result[4],
                    'duration': f"{result[6]} to {result[7]}" if result[6] and result[7] else "TBD",
                    'start_date': result[6] or "TBD",
                    'company': os.getenv("COMPANY_NAME", "Pensees Company"),
                    'sender_name': self.sender_name,
                    'employment_type': 'Full-time' if result[5] == 'FULLTIME' else 'Part-time',
                    'from_date': result[6],
                    'to_date': result[7]
                }
            return None
            
        except Exception as e:
            print(f"Error fetching candidate info: {e}")
            return None
    
    def render_template(self, template: str, variables: Dict[str, str]) -> str:
        """Replace template variables with actual values using your {variable} format."""
        rendered = template
        for key, value in variables.items():
            placeholder = f"{{{key}}}"
            rendered = rendered.replace(placeholder, str(value or ''))
        return rendered
    
    def send_email(self, to_email: str, subject: str, body: str) -> bool:
        """Send email using Gmail SMTP."""
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = f"{self.sender_name} <{self.sender_email}>"
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Add body to email
            msg.attach(MIMEText(body, 'plain'))
            
            # Create SMTP session
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()  # Enable security
            server.login(self.sender_email, self.sender_password)
            
            # Send email
            server.send_message(msg)
            server.quit()
            
            print(f"✅ Email sent successfully to {to_email}")
            return True
            
        except Exception as e:
            print(f"❌ Error sending email via Gmail SMTP: {e}")
            return False
    
    def send_template_email(self, candidate_key: str, template_name: str) -> Dict[str, any]:
        """Send templated email to candidate using your existing template."""
        # Get template
        template = self.get_email_template(template_name)
        if not template:
            return {'success': False, 'error': f'Template {template_name} not found'}
        
        # Get candidate info
        candidate_info = self.get_candidate_info(candidate_key)
        if not candidate_info:
            return {'success': False, 'error': f'Candidate {candidate_key} not found'}
        
        # Render template
        rendered_subject = self.render_template(template['subject'], candidate_info)
        rendered_body = self.render_template(template['body'], candidate_info)
        
        # Send email
        success = self.send_email(candidate_info['email'], rendered_subject, rendered_body)
        
        if success:
            return {
                'success': True, 
                'message': f'Email sent successfully to {candidate_info["email"]} via Gmail SMTP',
                'subject': rendered_subject,
                'body': rendered_body
            }
        else:
            return {'success': False, 'error': 'Failed to send email via Gmail SMTP'}