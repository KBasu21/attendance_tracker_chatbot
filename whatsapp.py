import os
import requests
from dotenv import load_dotenv

load_dotenv()

# We no longer load MY_NUMBER because the bot handles multiple users dynamically!
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERSION = os.getenv("VERSION", "v18.0") # Use your specific Meta API version

HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

def get_url():
    return f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"

def send_text_message(text, recipient_number):
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_number,
        "type": "text",
        "text": {"body": text}
    }
    requests.post(get_url(), headers=HEADERS, json=payload)

def send_interactive_menu(recipient_number):
    """Sends the reusable list menu for routine, percentage, and targets."""
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_number,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "EchoRoll Menu"},
            "body": {"text": "Choose an option to check your stats. You can return to this menu anytime!"},
            "footer": {"text": "Select from the list below"},
            "action": {
                "button": "Open Menu",
                "sections": [
                    {
                        "title": "Your Dashboard",
                        "rows": [
                            {"id": "menu_routine", "title": "📅 Routine", "description": "See today's classes"},
                            {"id": "menu_percentage", "title": "📊 Percentage", "description": "View overall attendance"},
                            {"id": "menu_target", "title": "🎯 Target", "description": "Classes needed for 75%"}
                        ]
                    }
                ]
            }
        }
    }
    requests.post(get_url(), headers=HEADERS, json=payload)

def ask_attendance(subject_name, subject_code, recipient_number):
    """Sends the 3 buttons when a class ends."""
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": f"Class ended! Did you attend *{subject_name}* ({subject_code})?"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"present_{subject_code}_{subject_name}",
                            "title": "✅ Present"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"absent_{subject_code}_{subject_name}",
                            "title": "❌ Absent"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"cancelled_{subject_code}_{subject_name}",
                            "title": "🚫 Cancelled"
                        }
                    }
                ]
            }
        }
    }
    requests.post(get_url(), headers=HEADERS, json=payload)

def send_update_question(subject_code, subject_name, recipient_number):
    """Sends the lock/unlock options immediately after marking attendance."""
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": f"Attendance locked for {subject_code}. Do you want to unlock and change it?"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"lock_yes_{subject_code}",
                            "title": "🔓 Yes, change it"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"lock_no_{subject_code}",
                            "title": "🔒 No, keep it"
                        }
                    }
                ]
            }
        }
    }
    requests.post(get_url(), headers=HEADERS, json=payload)

def send_dynamic_absent_list(routine_data, current_day, recipient_number):
    """Generates a dynamic menu based on the user's specific classes for the day."""
    rows = []
    for cls in routine_data:
        rows.append({
            "id": f"bulk_absent_{cls['subject_code']}",
            "title": f"❌ {cls['subject_code']}",
            # Meta limits descriptions to 72 characters, so we slice it just in case
            "description": cls['subject_name'][:72] 
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_number,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "Selective Absent Menu"},
            "body": {"text": f"Select the classes you are missing today ({current_day}).\n\n*Note: You can open this menu multiple times to select multiple subjects!*"},
            "footer": {"text": "Tap to select a class"},
            "action": {
                "button": "Choose Subject",
                "sections": [
                    {
                        "title": "Today's Classes",
                        "rows": rows
                    }
                ]
            }
        }
    }
    requests.post(get_url(), headers=HEADERS, json=payload)