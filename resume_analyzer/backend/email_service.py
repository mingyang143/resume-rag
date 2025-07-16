import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Optional
from dotenv import load_dotenv
from ..ingestion.helpers import connect_postgres, load_env_vars
import datetime
from datetime import datetime, timedelta  # Add this line
from dateutil import parser
from dateutil.relativedelta import relativedelta
import re

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
        

    def calculate_duration_months(self, start_date_str: str, end_date_str: str) -> str:
        """Calculate duration in months between two dates"""
        try:
            # Parse dates flexibly
            start_date = parser.parse(start_date_str, fuzzy=True)
            end_date = parser.parse(end_date_str, fuzzy=True)
            
            # Calculate difference
            diff = relativedelta(end_date, start_date)
            
            # Format the result
            if diff.years > 0:
                if diff.months > 0:
                    return f"{diff.years} year{'s' if diff.years > 1 else ''} and {diff.months} month{'s' if diff.months > 1 else ''}"
                else:
                    return f"{diff.years} year{'s' if diff.years > 1 else ''}"
            else:
                return f"{diff.months} month{'s' if diff.months != 1 else ''}"
                
        except Exception as e:
            print(f"Error calculating duration: {e}")
            return "duration to be determined"
    
    
    # def send_template_email_with_fields(self, candidate_key: str, template_type: str, extracted_fields: Dict[str, str]) -> Dict[str, any]:
    #     """Send email using template with fields extracted from user prompt"""
        
    #      # ADD DEBUG PRINT HERE
    #     print("="*50)
    #     print(f"DEBUG: Extracted fields: {extracted_fields}")
    #     print("="*50)
        
    #     try:
    #         # Get candidate info from database
    #         candidate_info = self.get_candidate_info(candidate_key)
    #         if not candidate_info:
    #             return {
    #                 'success': False,
    #                 'error': f'Candidate {candidate_key} not found in database'
    #             }
                
    #         # DEBUG: Check what's in the database
    #         print("="*50)
    #         print("DEBUG: Database values for candidate:")
    #         print(f"  part_or_full: '{candidate_info.get('part_or_full')}'")
    #         print(f"  employment_type: '{candidate_info.get('employment_type')}'")
    #         print("="*50)
            
    #         # Get email template
    #         template = self.get_email_template(template_type)
    #         if not template:
    #             return {
    #                 'success': False, 
    #                 'error': f'Email template {template_type} not found'
    #             }
            
    #         # Prepare template variables with extracted fields and database defaults
    #         template_variables = {
    #             'candidate_name': candidate_info.get('candidate_name', candidate_key),
    #             'company': self.sender_name.split()[0] if self.sender_name else 'Our Company',
    #             'sender_name': self.sender_name
    #         }
            
    #         # Handle job offer fields  
    #         if template_type == 'offer_template':
    #             # Position: use extracted or database default
    #             if extracted_fields.get('position'):
    #                 template_variables['position'] = extracted_fields['position']
    #             elif candidate_info.get('applied_position'):
    #                 template_variables['position'] = candidate_info['applied_position']
    #             else:
    #                 template_variables['position'] = 'the advertised position'
                
    #             # Required fields for offer
    #             missing_fields = []
    #             required_offer_fields = ['start_date', 'salary']
                
    #             # Check for start_date and salary (always required)
    #             for field in required_offer_fields:
    #                 if extracted_fields.get(field):
    #                     # Format salary with $ symbol if missing
    #                     if field == 'salary':
    #                         salary_value = extracted_fields[field]
    #                         # Add $ if not already present
    #                         if not salary_value.startswith('$'):
    #                             # Check if it's just a number
    #                             try:
    #                                 # If it's a pure number, add $/month
    #                                 float(salary_value)
    #                                 template_variables[field] = f"${salary_value}/month"
    #                             except ValueError:
    #                                 # If it contains text, just add $
    #                                 template_variables[field] = f"${salary_value}"
    #                         else:
    #                             template_variables[field] = salary_value
    #                     else:
    #                         template_variables[field] = extracted_fields[field]
    #                 else:
    #                     missing_fields.append(field)

                
    #             # Handle duration and end_date logic
    #             if extracted_fields.get('end_date') and extracted_fields.get('start_date'):
    #                 # Both start and end dates provided - calculate duration
    #                 start_date = extracted_fields['start_date']
    #                 end_date = extracted_fields['end_date']
                    
    #                 try:
    #                     parsed_start = parser.parse(start_date, fuzzy=True)
    #                     parsed_end = parser.parse(end_date, fuzzy=True)
                        
    #                     # Calculate duration
    #                     diff = relativedelta(parsed_end, parsed_start)
    #                     duration_text = f"{diff.months} months" if diff.months > 0 else "less than 1 month"
                        
    #                     # Format nicely
    #                     start_formatted = parsed_start.strftime('%B %d, %Y')
    #                     end_formatted = parsed_end.strftime('%B %d, %Y')
                        
    #                     template_variables['duration'] = f"{duration_text} ({start_formatted} - {end_formatted})"
    #                     template_variables['start_date'] = start_formatted
    #                     template_variables['end_date'] = end_formatted
                        
    #                 except Exception as e:
    #                     print(f"Error parsing dates: {e}")
    #                     template_variables['duration'] = f"from {start_date} to {end_date}"
    #                     template_variables['start_date'] = start_date
    #                     template_variables['end_date'] = end_date
                    
    #             elif extracted_fields.get('duration') and extracted_fields.get('start_date'):
    #                 # Duration provided but no end date - calculate end date and show duration properly
    #                 start_date = extracted_fields['start_date']
    #                 duration = extracted_fields['duration']
                    
    #                 try:
    #                     # Parse start date - handle relative dates like "Monday"
    #                     parsed_start = None
                        
    #                     # Handle relative dates like "Monday", "tuesday", etc.
    #                     if start_date.lower() in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
    #                         # Find next occurrence of this weekday
    #                         today = datetime.now()
    #                         weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    #                         target_weekday = weekdays.index(start_date.lower())
    #                         days_ahead = target_weekday - today.weekday()
    #                         if days_ahead <= 0:  # Target day already happened this week
    #                             days_ahead += 7
    #                         parsed_start = today + timedelta(days=days_ahead)
    #                     else:
    #                         # Regular date parsing
    #                         parsed_start = parser.parse(start_date, fuzzy=True)
                        
    #                     # Extract number of months from duration string OR handle special cases
    #                     duration_match = re.search(r'(\d+)\s*(month|months)', duration.lower())
                        
    #                     if duration_match:
    #                         # Regular "X months" format
    #                         months_to_add = int(duration_match.group(1))
    #                         calculated_end = parsed_start + relativedelta(months=months_to_add)
                            
    #                         # Format dates nicely
    #                         start_formatted = parsed_start.strftime('%B %d, %Y')
    #                         end_formatted = calculated_end.strftime('%B %d, %Y')
                            
    #                         template_variables['duration'] = f"{months_to_add} months ({start_formatted} - {end_formatted})"
    #                         template_variables['start_date'] = start_formatted
    #                         template_variables['end_date'] = end_formatted
                            
    #                     elif any(keyword in duration.lower() for keyword in ['summer', 'winter', 'internship', 'atap', 'sip']):
    #                         # Handle special program durations with different defaults
    #                         if 'summer' in duration.lower():
    #                             months_to_add = 3  # Summer internships are typically 3 months
    #                             calculated_end = parsed_start + relativedelta(months=months_to_add)
    #                             start_formatted = parsed_start.strftime('%B %d, %Y')
    #                             end_formatted = calculated_end.strftime('%B %d, %Y')
    #                             template_variables['duration'] = f"{duration} - {months_to_add} months ({start_formatted} - {end_formatted})"
    #                             template_variables['start_date'] = start_formatted
    #                             template_variables['end_date'] = end_formatted
                                
    #                         elif 'atap' in duration.lower():
    #                             months_to_add = 6  # ATAP program is 6 months
    #                             calculated_end = parsed_start + relativedelta(months=months_to_add)
    #                             start_formatted = parsed_start.strftime('%B %d, %Y')
    #                             end_formatted = calculated_end.strftime('%B %d, %Y')
    #                             template_variables['duration'] = f"ATAP program - 6 months ({start_formatted} - {end_formatted})"
    #                             template_variables['start_date'] = start_formatted
    #                             template_variables['end_date'] = end_formatted
                                
    #                         elif 'sip' in duration.lower():
    #                              # SIP program is 3 months from start date
    #                             months_to_add = 3  # SIP program is 3 months
    #                             calculated_end = parsed_start + relativedelta(months=months_to_add)
    #                             start_formatted = parsed_start.strftime('%B %d, %Y')
    #                             end_formatted = calculated_end.strftime('%B %d, %Y')
    #                             template_variables['duration'] = f"SIP program - 3 months ({start_formatted} - {end_formatted})"
    #                             template_variables['start_date'] = start_formatted
    #                             template_variables['end_date'] = end_formatted
                                
    #                         else:
    #                             # General internship - 3 months default
    #                             months_to_add = 3
    #                             calculated_end = parsed_start + relativedelta(months=months_to_add)
    #                             start_formatted = parsed_start.strftime('%B %d, %Y')
    #                             end_formatted = calculated_end.strftime('%B %d, %Y')
    #                             template_variables['duration'] = f"{duration} - {months_to_add} months ({start_formatted} - {end_formatted})"
    #                             template_variables['start_date'] = start_formatted
    #                             template_variables['end_date'] = end_formatted

                            
    #                     else:
    #                         # Fallback for other duration formats
    #                         template_variables['duration'] = duration
    #                         template_variables['start_date'] = parsed_start.strftime('%B %d, %Y') if parsed_start else start_date
    #                         template_variables['end_date'] = "to be determined"

                    
    #                 except Exception as e:
    #                     print(f"Error calculating end date: {e}")
    #                     template_variables['duration'] = duration
    #                     template_variables['start_date'] = start_date
    #                     template_variables['end_date'] = "to be determined"

    #             elif candidate_info.get('from_date') and candidate_info.get('to_date'):
    #                 # No extracted dates, fall back to database dates
    #                 calculated_duration = self.calculate_duration_months(
    #                     candidate_info['from_date'], 
    #                     candidate_info['to_date']
    #                 )
    #                 template_variables['duration'] = f"{calculated_duration} ({candidate_info['from_date']} - {candidate_info['to_date']})"
    #                 template_variables['start_date'] = candidate_info['from_date']
    #                 template_variables['end_date'] = candidate_info['to_date']
                    
    #             else:
    #                 # No duration information available
    #                 missing_fields.append('duration or end_date')

    #             # Try to get salary from database if not provided
    #             if 'salary' in missing_fields and candidate_info.get('salary') and candidate_info['salary'] != 'any':
    #                 template_variables['salary'] = f"${candidate_info['salary']}/month"
    #                 missing_fields.remove('salary')
                
    #             if missing_fields:
    #                 return {
    #                     'success': False,
    #                     'error': f'Missing required fields for job offer: {", ".join(missing_fields)}. Please specify: {", ".join(missing_fields)} in your message.'
    #                 }
                
    #             # Set employment type - use extracted field or database default
    #             if extracted_fields.get('employment_type'):
    #                 # Normalize the extracted employment type
    #                 emp_type = extracted_fields['employment_type'].lower()
    #                 if emp_type in ['part-time', 'pt', 'part time', 'parttime']:
    #                     template_variables['employment_type'] = 'Part-time'
    #                 elif emp_type in ['full-time', 'ft', 'full time', 'fulltime']:
    #                     template_variables['employment_type'] = 'Full-time'
    #                 else:
    #                     template_variables['employment_type'] = extracted_fields['employment_type']
    #             else:
    #                 # Fall back to database value with more robust handling
    #                 db_employment = candidate_info.get('part_or_full', '')
    #                 if db_employment and db_employment.upper() not in ['NONE', 'NULL', '']:
    #                     if db_employment.upper() in ['PARTTIME', 'PT', 'PART-TIME', 'PART TIME']:
    #                         template_variables['employment_type'] = 'Part-time'
    #                     elif db_employment.upper() in ['FULLTIME', 'FT', 'FULL-TIME', 'FULL TIME']:
    #                         template_variables['employment_type'] = 'Full-time'
    #                     else:
    #                         template_variables['employment_type'] = db_employment
    #                 else:
    #                     # Use the employment_type from get_candidate_info as fallback
    #                     template_variables['employment_type'] = candidate_info.get('employment_type', 'Full-time')

    #         # Handle interview invitation fields (existing code)
    #         elif template_type == 'interview_invitation':
    #             # ... existing interview code remains the same ...
    #             pass
            
    #         # Render the email template
    #         subject = self.render_template(template['subject'], template_variables)
            
    #         # DEBUG: Print template variables
    #         print("="*50)
    #         print("DEBUG: Template variables before rendering:")
    #         for key, value in template_variables.items():
    #             print(f"  {key}: {value}")
    #         print("="*50)
            
    #         body = self.render_template(template['body'], template_variables)
            
    #         # Send the email
    #         success = self.send_email(candidate_info['email'], subject, body)
            
    #         if success:
    #             return {
    #                 'success': True,
    #                 'message': f'{template_type.replace("_", " ").title()} sent successfully to {candidate_info["email"]}',
    #                 'subject': subject,
    #                 'body': body
    #             }
    #         else:
    #             return {
    #                 'success': False,
    #                 'error': 'Failed to send email via SMTP'
    #             }
                
    #     except Exception as e:
    #         return {
    #             'success': False,
    #             'error': f'Error sending email: {str(e)}'
    #         }


    def send_template_email_with_fields(self, candidate_key: str, template_type: str, extracted_fields: Dict[str, str], preview_only: bool = False) -> Dict[str, any]:
        """Send email using template with fields extracted from user prompt"""
        
         # ADD DEBUG PRINT HERE
        print("="*50)
        print(f"DEBUG: Extracted fields: {extracted_fields}")
        print("="*50)
        
        try:
            # Get candidate info from database
            candidate_info = self.get_candidate_info(candidate_key)
            if not candidate_info:
                return {
                    'success': False,
                    'error': f'Candidate {candidate_key} not found in database'
                }
                
            # DEBUG: Check what's in the database
            print("="*50)
            print("DEBUG: Database values for candidate:")
            print(f"  part_or_full: '{candidate_info.get('part_or_full')}'")
            print(f"  employment_type: '{candidate_info.get('employment_type')}'")
            print("="*50)
            
            # Get email template
            template = self.get_email_template(template_type)
            if not template:
                return {
                    'success': False, 
                    'error': f'Email template {template_type} not found'
                }
            
            # Prepare template variables with extracted fields and database defaults
            template_variables = {
                'candidate_name': candidate_info.get('candidate_name', candidate_key),
                'company': self.sender_name.split()[0] if self.sender_name else 'Our Company',
                'sender_name': self.sender_name
            }
            
            # Handle job offer fields  
            if template_type == 'offer_template':
                # Position: use extracted or database default
                if extracted_fields.get('position'):
                    template_variables['position'] = extracted_fields['position']
                elif candidate_info.get('applied_position'):
                    template_variables['position'] = candidate_info['applied_position']
                else:
                    template_variables['position'] = 'the advertised position'
                
                # Required fields for offer
                missing_fields = []
                required_offer_fields = ['start_date', 'salary']
                
                # Check for start_date and salary (always required)
                for field in required_offer_fields:
                    if extracted_fields.get(field):
                        # Format salary with $ symbol if missing
                        if field == 'salary':
                            salary_value = extracted_fields[field]
                            # Add $ if not already present
                            if not salary_value.startswith('$'):
                                # Check if it's just a number
                                try:
                                    # If it's a pure number, add $/month
                                    float(salary_value)
                                    template_variables[field] = f"${salary_value}/month"
                                except ValueError:
                                    # If it contains text, just add $
                                    template_variables[field] = f"${salary_value}"
                            else:
                                template_variables[field] = salary_value
                        else:
                            template_variables[field] = extracted_fields[field]
                    else:
                        missing_fields.append(field)

                # Handle duration and end_date logic
                if extracted_fields.get('end_date') and extracted_fields.get('start_date'):
                    # Both start and end dates provided - calculate duration
                    start_date = extracted_fields['start_date']
                    end_date = extracted_fields['end_date']
                    
                    try:
                        parsed_start = parser.parse(start_date, fuzzy=True)
                        parsed_end = parser.parse(end_date, fuzzy=True)
                        
                        # Calculate duration
                        diff = relativedelta(parsed_end, parsed_start)
                        duration_text = f"{diff.months} months" if diff.months > 0 else "less than 1 month"
                        
                        # Format nicely
                        start_formatted = parsed_start.strftime('%B %d, %Y')
                        end_formatted = parsed_end.strftime('%B %d, %Y')
                        
                        template_variables['duration'] = f"{duration_text} ({start_formatted} - {end_formatted})"
                        template_variables['start_date'] = start_formatted
                        template_variables['end_date'] = end_formatted
                        
                    except Exception as e:
                        print(f"Error parsing dates: {e}")
                        template_variables['duration'] = f"from {start_date} to {end_date}"
                        template_variables['start_date'] = start_date
                        template_variables['end_date'] = end_date
                    
                elif extracted_fields.get('duration') and extracted_fields.get('start_date'):
                    # Duration provided but no end date - calculate end date and show duration properly
                    start_date = extracted_fields['start_date']
                    duration = extracted_fields['duration']
                    
                    try:
                        # Parse start date - handle relative dates like "Monday"
                        parsed_start = None
                        
                        # Handle relative dates like "Monday", "tuesday", etc.
                        if start_date.lower() in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                            # Find next occurrence of this weekday
                            today = datetime.now()
                            weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                            target_weekday = weekdays.index(start_date.lower())
                            days_ahead = target_weekday - today.weekday()
                            if days_ahead <= 0:  # Target day already happened this week
                                days_ahead += 7
                            parsed_start = today + timedelta(days=days_ahead)
                        else:
                            # Regular date parsing
                            parsed_start = parser.parse(start_date, fuzzy=True)
                        
                        # Extract number of months from duration string OR handle special cases
                        duration_match = re.search(r'(\d+)\s*(month|months)', duration.lower())
                        
                        if duration_match:
                            # Regular "X months" format
                            months_to_add = int(duration_match.group(1))
                            calculated_end = parsed_start + relativedelta(months=months_to_add)
                            
                            # Format dates nicely
                            start_formatted = parsed_start.strftime('%B %d, %Y')
                            end_formatted = calculated_end.strftime('%B %d, %Y')
                            
                            template_variables['duration'] = f"{months_to_add} months ({start_formatted} - {end_formatted})"
                            template_variables['start_date'] = start_formatted
                            template_variables['end_date'] = end_formatted
                            
                        elif any(keyword in duration.lower() for keyword in ['summer', 'winter', 'internship', 'atap', 'sip']):
                            # Handle special program durations with different defaults
                            if 'summer' in duration.lower():
                                months_to_add = 3  # Summer internships are typically 3 months
                                calculated_end = parsed_start + relativedelta(months=months_to_add)
                                start_formatted = parsed_start.strftime('%B %d, %Y')
                                end_formatted = calculated_end.strftime('%B %d, %Y')
                                template_variables['duration'] = f"{duration} - {months_to_add} months ({start_formatted} - {end_formatted})"
                                template_variables['start_date'] = start_formatted
                                template_variables['end_date'] = end_formatted
                                
                            elif 'atap' in duration.lower():
                                months_to_add = 6  # ATAP program is 6 months
                                calculated_end = parsed_start + relativedelta(months=months_to_add)
                                start_formatted = parsed_start.strftime('%B %d, %Y')
                                end_formatted = calculated_end.strftime('%B %d, %Y')
                                template_variables['duration'] = f"ATAP program - 6 months ({start_formatted} - {end_formatted})"
                                template_variables['start_date'] = start_formatted
                                template_variables['end_date'] = end_formatted
                                
                            elif 'sip' in duration.lower():
                                 # SIP program is 3 months from start date
                                months_to_add = 3  # SIP program is 3 months
                                calculated_end = parsed_start + relativedelta(months=months_to_add)
                                start_formatted = parsed_start.strftime('%B %d, %Y')
                                end_formatted = calculated_end.strftime('%B %d, %Y')
                                template_variables['duration'] = f"SIP program - 3 months ({start_formatted} - {end_formatted})"
                                template_variables['start_date'] = start_formatted
                                template_variables['end_date'] = end_formatted
                                
                            else:
                                # General internship - 3 months default
                                months_to_add = 3
                                calculated_end = parsed_start + relativedelta(months=months_to_add)
                                start_formatted = parsed_start.strftime('%B %d, %Y')
                                end_formatted = calculated_end.strftime('%B %d, %Y')
                                template_variables['duration'] = f"{duration} - {months_to_add} months ({start_formatted} - {end_formatted})"
                                template_variables['start_date'] = start_formatted
                                template_variables['end_date'] = end_formatted

                        else:
                            # Fallback for other duration formats
                            template_variables['duration'] = duration
                            template_variables['start_date'] = parsed_start.strftime('%B %d, %Y') if parsed_start else start_date
                            template_variables['end_date'] = "to be determined"

                    except Exception as e:
                        print(f"Error calculating end date: {e}")
                        template_variables['duration'] = duration
                        template_variables['start_date'] = start_date
                        template_variables['end_date'] = "to be determined"

                elif candidate_info.get('from_date') and candidate_info.get('to_date'):
                    # No extracted dates, fall back to database dates
                    calculated_duration = self.calculate_duration_months(
                        candidate_info['from_date'], 
                        candidate_info['to_date']
                    )
                    template_variables['duration'] = f"{calculated_duration} ({candidate_info['from_date']} - {candidate_info['to_date']})"
                    template_variables['start_date'] = candidate_info['from_date']
                    template_variables['end_date'] = candidate_info['to_date']
                    
                else:
                    # No duration information available
                    missing_fields.append('duration or end_date')

                # Try to get salary from database if not provided
                if 'salary' in missing_fields and candidate_info.get('salary') and candidate_info['salary'] != 'any':
                    template_variables['salary'] = f"${candidate_info['salary']}/month"
                    missing_fields.remove('salary')
                
                if missing_fields:
                    return {
                        'success': False,
                        'error': f'Missing required fields for job offer: {", ".join(missing_fields)}. Please specify: {", ".join(missing_fields)} in your message.'
                    }
                
                # Set employment type - use extracted field or database default
                if extracted_fields.get('employment_type'):
                    # Normalize the extracted employment type
                    emp_type = extracted_fields['employment_type'].lower()
                    if emp_type in ['part-time', 'pt', 'part time', 'parttime']:
                        template_variables['employment_type'] = 'Part-time'
                    elif emp_type in ['full-time', 'ft', 'full time', 'fulltime']:
                        template_variables['employment_type'] = 'Full-time'
                    else:
                        template_variables['employment_type'] = extracted_fields['employment_type']
                else:
                    # Fall back to database value with more robust handling
                    db_employment = candidate_info.get('part_or_full', '')
                    if db_employment and db_employment.upper() not in ['NONE', 'NULL', '']:
                        if db_employment.upper() in ['PARTTIME', 'PT', 'PART-TIME', 'PART TIME']:
                            template_variables['employment_type'] = 'Part-time'
                        elif db_employment.upper() in ['FULLTIME', 'FT', 'FULL-TIME', 'FULL TIME']:
                            template_variables['employment_type'] = 'Full-time'
                        else:
                            template_variables['employment_type'] = db_employment
                    else:
                        # Use the employment_type from get_candidate_info as fallback
                        template_variables['employment_type'] = candidate_info.get('employment_type', 'Full-time')

            # Handle rejection email fields
            elif template_type == 'rejection_email':
                # Position: use extracted or database default
                if extracted_fields.get('position'):
                    template_variables['position'] = extracted_fields['position']
                elif candidate_info.get('applied_position'):
                    template_variables['position'] = candidate_info['applied_position']
                else:
                    template_variables['position'] = 'the position you applied for'
                
                # No other fields required for rejection emails
                
            
            # Handle interview invitation fields
            elif template_type == 'interview_invitation':
                # Required fields for interview
                missing_fields = []
                required_interview_fields = ['date', 'time']
                
                # Check for required fields (date and time)
                for field in required_interview_fields:
                    if extracted_fields.get(field):
                        template_variables[field] = extracted_fields[field]
                    else:
                        missing_fields.append(field)
                
                # Position: use extracted or database default
                if extracted_fields.get('position'):
                    template_variables['position'] = extracted_fields['position']
                elif candidate_info.get('applied_position'):
                    template_variables['position'] = candidate_info['applied_position']
                else:
                    template_variables['position'] = 'the advertised position'
                
                # Format: default to "in-person" if not specified
                if extracted_fields.get('format'):
                    # Normalize format values
                    format_value = extracted_fields['format'].lower()
                    if format_value in ['zoom', 'online', 'virtual', 'teams', 'meet', 'video call']:
                        template_variables['format'] = 'online'
                    elif format_value in ['in-person', 'physical', 'office', 'on-site', 'face-to-face']:
                        template_variables['format'] = 'in-person'
                    else:
                        template_variables['format'] = extracted_fields['format']
                else:
                    template_variables['format'] = 'in-person'  # Default
                
                # Duration: default to "1 hour" if not specified
                if extracted_fields.get('duration'):
                    # Normalize duration values
                    duration_value = extracted_fields['duration'].lower()
                    # Handle various formats like "45 minutes", "1 hour", "30 mins", "1.5 hours"
                    if 'hour' in duration_value or 'hr' in duration_value:
                        template_variables['duration'] = extracted_fields['duration']
                    elif 'minute' in duration_value or 'min' in duration_value:
                        template_variables['duration'] = extracted_fields['duration']
                    else:
                        # If just a number, assume minutes
                        try:
                            num = int(extracted_fields['duration'])
                            if num < 5:  # Probably hours
                                template_variables['duration'] = f"{num} hour{'s' if num > 1 else ''}"
                            else:  # Probably minutes
                                template_variables['duration'] = f"{num} minutes"
                        except ValueError:
                            template_variables['duration'] = extracted_fields['duration']
                else:
                    template_variables['duration'] = '1 hour'  # Default
                
                # Check if we have all required fields
                if missing_fields:
                    return {
                        'success': False,
                        'error': f'Missing required fields for interview invitation: {", ".join(missing_fields)}. Please specify: {", ".join(missing_fields)} in your message.'
                    }
                
                # Format the date and time nicely if possible
                # try:
                #     # Try to parse and format the date
                #     if extracted_fields.get('date'):
                #         parsed_date = parser.parse(extracted_fields['date'], fuzzy=True)
                #         template_variables['date'] = parsed_date.strftime('%B %d, %Y')  # e.g., "January 15, 2025"
                # except Exception as e:
                #     # Keep original format if parsing fails
                #     print(f"Could not parse date '{extracted_fields.get('date')}': {e}")
                #     template_variables['date'] = extracted_fields.get('date', '')
                
                # Format the date and time nicely if possible
                try:
                    # Try to parse and format the date
                    if extracted_fields.get('date'):
                        date_text = extracted_fields['date'].lower().strip()
                        
                        # Handle "tomorrow" case
                        if date_text == 'tomorrow':
                            from datetime import datetime, timedelta
                            
                            tomorrow = datetime.now() + timedelta(days=1)
                            template_variables['date'] = tomorrow.strftime('%B %d, %Y')
                            
                        # Handle "today" case
                        elif date_text == 'today':
                            from datetime import datetime
                            
                            today = datetime.now()
                            template_variables['date'] = today.strftime('%B %d, %Y')
                            
                        # Handle "next [day]" cases manually
                        elif date_text.startswith('next '):
                            from datetime import datetime, timedelta
                            import calendar
                            
                            day_name = date_text.replace('next ', '').strip()
                            weekdays = {
                                'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                                'friday': 4, 'saturday': 5, 'sunday': 6
                            }
                            
                            if day_name in weekdays:
                                today = datetime.now()
                                target_weekday = weekdays[day_name]
                                current_weekday = today.weekday()
                                
                                # For "next [day]", we ALWAYS want the next week's occurrence
                                days_ahead = target_weekday - current_weekday
                                if days_ahead <= 0:  # Target day already happened this week or is today
                                    days_ahead += 7  # Go to next week
                                else:
                                    days_ahead += 7  # Still go to next week even if it hasn't happened yet
                                
                                target_date = today + timedelta(days=days_ahead)
                                template_variables['date'] = target_date.strftime('%B %d, %Y')
                            else:
                                # Fall back to original parsing
                                parsed_date = parser.parse(extracted_fields['date'], fuzzy=True)
                                template_variables['date'] = parsed_date.strftime('%B %d, %Y')
                                
                        # Handle "this [day]" cases
                        elif date_text.startswith('this '):
                            from datetime import datetime, timedelta
                            
                            day_name = date_text.replace('this ', '').strip()
                            weekdays = {
                                'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                                'friday': 4, 'saturday': 5, 'sunday': 6
                            }
                            
                            if day_name in weekdays:
                                today = datetime.now()
                                target_weekday = weekdays[day_name]
                                current_weekday = today.weekday()
                                
                                # For "this [day]", we want this week's occurrence if it hasn't passed
                                days_ahead = target_weekday - current_weekday
                                if days_ahead < 0:  # Target day already happened this week
                                    days_ahead += 7  # Go to next week
                                # If days_ahead == 0, it's today
                                # If days_ahead > 0, it's later this week
                                
                                target_date = today + timedelta(days=days_ahead)
                                template_variables['date'] = target_date.strftime('%B %d, %Y')
                            else:
                                # Fall back to original parsing
                                parsed_date = parser.parse(extracted_fields['date'], fuzzy=True)
                                template_variables['date'] = parsed_date.strftime('%B %d, %Y')
                                
                        else:
                            # Use dateutil parser for other formats (like "January 15", "15th", etc.)
                            parsed_date = parser.parse(extracted_fields['date'], fuzzy=True)
                            template_variables['date'] = parsed_date.strftime('%B %d, %Y')
                            
                except Exception as e:
                    # Keep original format if parsing fails
                    print(f"Could not parse date '{extracted_fields.get('date')}': {e}")
                    template_variables['date'] = extracted_fields.get('date', '')

            
            # Render the email template
            subject = self.render_template(template['subject'], template_variables)
            body = self.render_template(template['body'], template_variables)
            
            # DEBUG: Print template variables
            print("="*50)
            print("DEBUG: Template variables before rendering:")
            for key, value in template_variables.items():
                print(f"  {key}: {value}")
            print("="*50)
            
            # If preview_only, return the rendered email without sending
            if preview_only:
                return {
                    'success': True,
                    'preview_mode': True,
                    'candidate_key': candidate_key,
                    'template_type': template_type,
                    'extracted_fields': extracted_fields,
                    'recipient_email': candidate_info['email'],
                    'subject': subject,
                    'body': body,
                    'message': 'Email preview ready. Reply with "send", "yes", or "confirm" to send the email.'
                }
            
            # Send the email
            success = self.send_email(candidate_info['email'], subject, body)
            
            if success:
                return {
                    'success': True,
                    'message': f'{template_type.replace("_", " ").title()} sent successfully to {candidate_info["email"]}',
                    'subject': subject,
                    'body': body
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to send email via SMTP'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'Error sending email: {str(e)}'
            }
