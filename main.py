import os
import math
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from datetime import datetime
from dotenv import load_dotenv
from database import supabase
from whatsapp import send_text_message, send_interactive_menu, send_update_question
from scheduler import start_scheduler


load_dotenv()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield

app = FastAPI(lifespan=lifespan)

@app.on_event("startup")
def startup_event():
    start_scheduler()

@app.get("/")
def home():
    return {"status": "Attendance Bot is running!"}

@app.get("/webhook")
def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified!")
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Verfication failed", status_code=403)

@app.post("/webhook")
async def receive_message(request: Request):
    data = await request.json()

    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if messages:
            msg = messages[0]
            
            # ==========================================
            # 1. HANDLE PLAIN TEXT MESSAGES ("Hi", etc.)
            # ==========================================
            if msg.get("type") == "text":
                text = msg["text"]["body"].strip().upper()
                print(f"Bot received text: {text}")
                
                if text == "HI":
                    send_interactive_menu()
                elif text == "ROUTINE":
                    handle_routine()
                elif text == "PERCENTAGE":
                    handle_percentage()
                elif text == "TARGET":
                    handle_target()

            # ==========================================
            # 2. HANDLE INTERACTIVE BUTTON CLICKS
            # ==========================================
            elif msg.get("type") == "interactive":
                button_id = msg["interactive"]["button_reply"]["id"]
                today_date = datetime.now().strftime("%Y-%m-%d")

                # --- A. Menu Buttons (ROUTINE, etc.) ---
                if button_id.startswith("menu_"):
                    if button_id == "menu_routine": handle_routine()
                    elif button_id == "menu_percentage": handle_percentage()
                    elif button_id == "menu_target": handle_target()

                # --- B. The "Update?" Question Logic ---
                elif button_id.startswith("lock_"):
                    action, subject_code = button_id.replace("lock_", "").split("_")
                    
                    if action == "yes":
                        # Unlock the record so the user can click the previous buttons again
                        supabase.table("attendance_logs").update({"is_locked": False})\
                            .eq("date", today_date).eq("subject_code", subject_code).execute()
                        send_text_message(f"🔓 Attendance for {subject_code} is now unlocked. You can use the previous buttons to change it.")
                    else:
                        # Keep it locked
                        send_text_message(f"✅ Attendance for {subject_code} finalized.")

                # --- C. Attendance Marking Logic (With Lock Check) ---
                elif button_id.startswith(("present_", "absent_", "cancelled_")):
                    status, subject_code, subject_name = button_id.split("_", 2)

                    # CHECK IF LOCKED:
                    existing = supabase.table("attendance_logs").select("is_locked")\
                        .eq("date", today_date).eq("subject_code", subject_code).execute()
                    
                    # If record exists and is locked, ignore the click completely
                    if existing.data and existing.data[0]['is_locked'] == True:
                        print(f"Ignored click: {subject_code} is locked.")
                        return {"status": "ignored"}

                    # Otherwise, save the data and lock it immediately
                    log_data = {
                        "date": today_date,
                        "subject_code": subject_code,
                        "subject_name": subject_name,
                        "status": status.capitalize(),
                        "is_locked": True  # Auto-lock after every click
                    }

                    supabase.table("attendance_logs").upsert(log_data, on_conflict="date,subject_code").execute()
                    
                    send_text_message(f"📝 Logged! Marked as {status.capitalize()} for {subject_name} ({subject_code}).")
                    
                    # Ask the user if they want to unlock it for updates
                    send_update_question(subject_code, subject_name)

    except Exception as e:
        print(f"Error processing webhook: {e}")

    return {"status": "success"}

# ==========================================
# HELPER FUNCTIONS FOR THE MENU
# ==========================================

def handle_routine():
    current_day = datetime.now().strftime("%A")
    response = supabase.table("routine").select("*").eq("day_of_week", current_day).order("start_time").execute()
    
    classes = response.data
    if not classes:
        send_text_message(f"No classes scheduled for today ({current_day})! Enjoy your day off. 🎉")
        return

    msg_text = f"📅 *Routine for {current_day}*\n\n"
    for cls in classes:
        prof = cls.get('professor_name') or "TBA"
        msg_text += f"🔹 *{cls['subject_name']}* ({cls['subject_code']})\n"
        msg_text += f"⏰ {cls['start_time']} - {cls['end_time']}\n"
        msg_text += f"👨‍🏫 Prof: {prof}\n\n"
        
    send_text_message(msg_text.strip())

def get_attendance_data():
    """Helper to fetch and group attendance data for Percentage and Target math."""
    response = supabase.table("attendance_logs").select("*").execute()
    logs = response.data
    
    subjects = {}
    for log in logs:
        # Ignore cancelled classes
        if log['status'] == 'Cancelled':
            continue
            
        code = log['subject_code']
        if code not in subjects:
            subjects[code] = {'name': log['subject_name'], 'present': 0, 'absent': 0}
            
        if log['status'] == 'Present':
            subjects[code]['present'] += 1
        elif log['status'] == 'Absent':
            subjects[code]['absent'] += 1
            
    return subjects

def handle_percentage():
    subjects = get_attendance_data()
    
    if not subjects:
        send_text_message("No attendance records found yet!")
        return
        
    msg_text = "📊 *Current Attendance Percentage*\n\n"
    for code, data in subjects.items():
        total = data['present'] + data['absent']
        if total == 0:
            continue
            
        percent = (data['present'] / total) * 100
        msg_text += f"🔹 *{data['name']}* ({code})\n"
        msg_text += f"📈 {round(percent, 2)}% ({data['present']}/{total} classes)\n\n"
        
    send_text_message(msg_text.strip())

def handle_target():
    subjects = get_attendance_data()
    
    if not subjects:
        send_text_message("No attendance records found yet!")
        return

    msg_text = "🎯 *Target to reach 75% Attendance*\n\n"
    for code, data in subjects.items():
        classes_attended = data['present']
        classes_held = data['present'] + data['absent']
        
        if classes_held == 0:
            continue
            
        current_percent = (classes_attended / classes_held) * 100
        
        msg_text += f"🔹 *{data['name']}* ({code})\n"
        
        if current_percent >= 75:
            msg_text += f"✅ Safe! Currently at {round(current_percent, 2)}%.\n\n"
        else:
            required_classes = ((0.75 * classes_held) - classes_attended) / 0.25
            classes_to_attend = math.ceil(required_classes) 
            msg_text += f"⚠️ Currently at {round(current_percent, 2)}%.\n"
            msg_text += f"🏃‍♂️ You must attend the next *{classes_to_attend}* classes without fail.\n\n"

    send_text_message(msg_text.strip())