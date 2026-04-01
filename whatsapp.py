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
            "type": "button",
            "body": {"text": "Welcome to EchoRoll! Choose one option:"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "menu_routine", "title": "ROUTINE"}},
                    {"type": "reply", "reply": {"id": "menu_percentage", "title": "PERCENTAGE"}},
                    {"type": "reply", "reply": {"id": "menu_target", "title": "TARGET"}},
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
            "body": {"text": f"Do you want to update the attendance for {subject_name}?"},
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
