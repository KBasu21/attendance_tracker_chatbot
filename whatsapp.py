import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
MY_NUMBER = os.getenv("MY_PHONE_NUMBER")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}
URL = f"https://graph.facebook.com/v22.0/{PHONE_ID}/messages"

def ask_attendance(subject_name: str, subject_code: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": MY_NUMBER,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": f"Did your {subject_name} class happen today? Were you present?"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": f"present_{subject_code}_{subject_name}", "title": "Present"}},
                    {"type": "reply", "reply": {"id": f"absent_{subject_code}_{subject_name}", "title": "Absent"}},
                    {"type": "reply", "reply": {"id": f"cancelled_{subject_code}_{subject_name}", "title": "Cancelled"}},
                ]
            }
        }
    }
    response = requests.post(URL, headers=HEADERS, json=payload)
    print(f"Meta API Response (Menu): {response.status_code} - {response.text}")
    return response.json()

def send_interactive_menu():
    payload = {
        "messaging_product": "whatsapp",
        "to": MY_NUMBER,
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
    response = requests.post(URL, headers=HEADERS, json=payload)
    print(f"Meta API Response (Menu): {response.status_code} - {response.text}")

def send_update_question(subject_code, subject_name):
    payload = {
        "messaging_product": "whatsapp",
        "to": MY_NUMBER,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": f"Do you want to change the attendance for {subject_name}?"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": f"lock_no_{subject_code}", "title": "No"}},
                    {"type": "reply", "reply": {"id": f"lock_yes_{subject_code}", "title": "Yes"}},
                ]
            }
        }
    }
    requests.post(URL, headers=HEADERS, json=payload)

def send_text_message(text: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": MY_NUMBER,
        "type": "text",
        "text": {"body": text}
    }
    response = requests.post(URL, headers=HEADERS, json=payload)
    print(f"Meta API Response (Menu): {response.status_code} - {response.text}")

def send_dynamic_absent_list(routine_data, current_day):
    # We build the list rows dynamically based on today's classes
    rows = []
    for cls in routine_data:
        rows.append({
            "id": f"bulk_absent_{cls['subject_code']}",
            "title": f"❌ {cls['subject_code']}",
            "description": cls['subject_name']
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": MY_NUMBER,
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
    import requests
    requests.post(URL, headers=HEADERS, json=payload)