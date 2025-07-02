import streamlit as st
from typing import Dict, List, Optional, Tuple
from ..backend.email_service import EmailService
from ..backend.helpers import detect_email_intent, fetch_candidate_keys

def handle_email_confirmation(user_input: str, email_service: EmailService) -> Tuple[Optional[str], bool]:
    """
    Handle email confirmation responses.
    
    Returns:
        Tuple[Optional[str], bool]: (reply_message, should_clear_pending)
    """
    if not st.session_state.get('pending_email'):
        return None, False
    
    user_response = user_input.lower().strip()
    
    # VERY STRICT: Only accept these exact phrases for confirmation
    confirmation_phrases = ['send', 'yes', 'confirm', 'ok', 'proceed', 'y']
    cancel_phrases = ['cancel', 'no', 'stop', 'abort', 'n']
    
    is_confirmation = user_response in confirmation_phrases
    is_cancellation = user_response in cancel_phrases
    
    if is_confirmation:
        return _send_pending_email(email_service), True
    elif is_cancellation:
        return "📧 Email sending cancelled.", True
    else:
        # Everything else gets the reminder
        return _generate_pending_email_reminder(user_input), False


def _send_pending_email(email_service: EmailService) -> str:
    """Send the pending email and return status message."""
    pending = st.session_state.pending_email
    
    with st.spinner(f"📧 Sending {pending['template_type'].replace('_', ' ')} to {pending['candidate_key']}..."):
        try:
            result = email_service.send_template_email_with_fields(
                pending['candidate_key'], 
                pending['template_type'], 
                pending['extracted_fields'],
                preview_only=False
            )

            if result['success']:
                # Show final confirmation in expander
                with st.expander("📧 Email Sent Details"):
                    st.write(f"**To:** {pending['recipient_email']}")
                    st.write(f"**Subject:** {result['subject']}")
                    st.text_area("Email Body:", result['body'], height=200)
                
                return f"✅ {result['message']}"
            else:
                return f"❌ {result['error']}"
                
        except Exception as e:
            return f"❌ Error sending email: {str(e)}"

def _generate_pending_email_reminder(user_input: str) -> str:
    """Generate reminder message for pending email."""
    pending = st.session_state.pending_email
    
    reply = f"⚠️ **Please respond to the pending email first!**\n\n"
    reply += f"There is an email to **{pending['candidate_key']}** waiting for your confirmation.\n\n"
    reply += "Please reply with:\n"
    reply += "• **'send'**, **'yes'**, **'confirm'**, **'ok'**, **'proceed'** to send the email\n"
    reply += "• **'cancel'**, **'no'**, **'stop'**, **'abort'** to cancel the email\n\n"
    reply += f"Your response '{user_input}' was not recognized as a clear confirmation or cancellation.\n"
    reply += "I cannot process other requests until you decide on this email."
    
    return reply

def handle_email_request(user_input: str, matched_files: List[str], email_service: EmailService) -> Optional[str]:
    """
    Handle new email requests and show preview.
    
    Returns:
        Optional[str]: Reply message if this was an email request, None otherwise
    """
    # Get current candidate keys
    filename_to_candidate = fetch_candidate_keys(matched_files)
    current_candidate_keys = list(set(filename_to_candidate.values()))
    
    print("----------------------------------------------------")
    print(f"📧 Checking email intent for: {user_input}")
    print("----------------------------------------------------")
    
    email_intent = detect_email_intent(user_input, current_candidate_keys)
    
    print("----------------------------------------------------")
    print(f"📧 Email intent detected: {email_intent}")
    print("----------------------------------------------------")

    if not email_intent['is_email_request']:
        return None
    
    # Handle email request
    template_type = email_intent['template_type']
    candidate_key = email_intent['candidate_key']
    extracted_fields = email_intent.get('extracted_fields', {})
    
    if not candidate_key:
        return f"❌ I understand you want to send an email, but I couldn't identify which candidate you're referring to. Available candidates in current results: {', '.join(current_candidate_keys)}"
    elif not template_type:
        return f"❌ I understand you want to send an email to {candidate_key}, but I couldn't determine what type of email. Available types: offer, rejection, interview."
    else:
        return _show_email_preview(candidate_key, template_type, extracted_fields, email_service)

def _show_email_preview(candidate_key: str, template_type: str, extracted_fields: Dict, email_service: EmailService) -> str:
    """Show email preview and store in session state."""
    with st.spinner(f"📧 Preparing {template_type.replace('_', ' ')} for {candidate_key}..."):
        try:
            result = email_service.send_template_email_with_fields(
                candidate_key, 
                template_type, 
                extracted_fields,
                preview_only=True
            )

            if result['success'] and result.get('preview_mode'):
                # Show email preview UI
                _display_email_preview(result, template_type)
                
                # Store pending email in session state
                st.session_state.pending_email = {
                    'candidate_key': candidate_key,
                    'template_type': template_type,
                    'extracted_fields': extracted_fields,
                    'recipient_email': result['recipient_email']
                }
                
                return "📧 Email Preview - Please review before sending:\n\n⚠️ **Confirmation Required:** Reply with **'send'**, **'yes'**, or **'confirm'** to send this email, or **'cancel'** to abort."
            else:
                return f"❌ {result.get('error', 'Failed to prepare email preview')}"
                
        except Exception as e:
            return f"❌ Error preparing email: {str(e)}"

def _display_email_preview(result: Dict, template_type: str) -> None:
    """Display the email preview UI components."""
    col1, col2 = st.columns([3, 1])
    with col1:
        st.write(f"**To:** {result['recipient_email']}")
        st.write(f"**Subject:** {result['subject']}")
    with col2:
        st.write(f"**Template:** {template_type}")
    
    # Show email body in expandable section
    with st.expander("📧 Full Email Preview", expanded=True):
        st.text_area("Email Body:", result['body'], height=300)

def process_user_input(user_input: str, matched_files: List[str], candidate_keys: List[str], email_service: EmailService) -> str:
    """
    Main function to process user input - handles email confirmation, email requests, or regular chat.
    
    Returns:
        str: Reply message
    """
    # First priority: Handle pending email confirmations
    if st.session_state.get('pending_email'):
        reply, should_clear = handle_email_confirmation(user_input, email_service)
        if should_clear:
            del st.session_state.pending_email
        # ALWAYS return the reply when there's a pending email (blocking other requests)
        return reply if reply is not None else _generate_pending_email_reminder(user_input)
    
    # Only proceed with other requests if there's NO pending email
    # Second priority: Handle new email requests
    email_reply = handle_email_request(user_input, matched_files, email_service)
    if email_reply:
        return email_reply
    
    # Third priority: Handle regular chat
    return _handle_regular_chat(user_input, candidate_keys)


def _handle_regular_chat(user_input: str, candidate_keys: List[str]) -> str:
    """Handle regular chat queries."""
    from ..backend.helpers import chat_with_resumes
    
    with st.spinner("🤔 Analyzing your question..."):
        try:
            result = chat_with_resumes(
                user_query=user_input,
                candidate_keys=candidate_keys,
                context_limit=3
            )
            
            reply = result["answer"]
            query_type = result["query_type"]
            skills_extracted = result.get("skills_extracted", [])
            candidates_analyzed = result.get("candidates_analyzed", [])
            
            # Add metadata to the response for transparency
            if query_type == "skill_matching" and skills_extracted:
                reply += f"\n\n*🔍 Skills identified: {', '.join(skills_extracted)}*"
            
            if candidates_analyzed:
                reply += f"\n\n*👥 Candidates analyzed: {', '.join(candidates_analyzed)}*"
            
            print("----------------------------------------------------")
            print(f"Chat response - Query type: {query_type}")
            print(f"Skills extracted: {skills_extracted}")
            print(f"Candidates analyzed: {candidates_analyzed}")
            print("----------------------------------------------------")
            
            return reply
            
        except Exception as e:
            print("----------------------------------------------------")
            print(f"Chat error: {e}")
            print("----------------------------------------------------")
            return f"❌ I encountered an error while processing your question: {str(e)}"