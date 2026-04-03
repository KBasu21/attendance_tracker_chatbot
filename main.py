import os
import math
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from datetime import datetime
from dotenv import load_dotenv
from database import supabase
from whatsapp import send_text_message, send_interactive_menu, send_update_question
from scheduler import start_scheduler, is_today_a_holiday


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
                raw_text = msg["text"]["body"].strip()
                print(f"Bot received text: {text}")
                
                if text == "HI":
                    send_interactive_menu()
                elif text == "ROUTINE":
                    handle_routine()
                elif text == "PERCENTAGE":
                    handle_percentage()
                elif text == "TARGET":
                    handle_target()
                elif text.startswith("CANCEL"):
                    handle_cancel(text)
                elif text.startswith("ADD HOLIDAY"):
                    handle_add_holiday(raw_text)
                elif text.startswith("REMOVE HOLIDAY"):
                    handle_remove_holiday(text)
                elif text.startswith("HISTORY"):
                    handle_history(text)

            # ==========================================
            # 2. HANDLE INTERACTIVE BUTTON CLICKS
            # ==========================================
            elif msg.get("type") == "interactive":
                interactive_obj = msg["interactive"]
                
                # Check if it's from a list (Reusable Menu) or a button (Attendance/Lock)
                if "list_reply" in interactive_obj:
                    button_id = interactive_obj["list_reply"]["id"]
                elif "button_reply" in interactive_obj:
                    button_id = interactive_obj["button_reply"]["id"]
                else:
                    return {"status": "ignored"}

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
    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    current_day = now.strftime("%A")
    
    if is_today_a_holiday(today_date):
        send_text_message("🌴 It's a holiday today! Chill out and enjoy your day off. 🎮🍿")
        return

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

def handle_cancel(command_text):
    today_date = datetime.now().strftime("%Y-%m-%d")
    current_day = datetime.now().strftime("%A")
    
    # 1. Get today's classes
    routine = supabase.table("routine").select("*").eq("day_of_week", current_day).execute()
    
    if not routine.data:
        send_text_message("You don't have any classes to cancel today!")
        return

    classes_to_cancel = []
    
    # 2. Check if it's "CANCEL ALL" or a specific code
    if command_text == "CANCEL ALL":
        classes_to_cancel = routine.data
        success_msg = "All classes for today have been"
    else:
        # Extract the specific code (e.g., "CANCEL CS401" -> "CS401")
        target_code = command_text.replace("CANCEL ", "").strip()
        
        # Search today's routine for that exact code
        for cls in routine.data:
            if cls['subject_code'] == target_code:
                classes_to_cancel.append(cls)
                
        if not classes_to_cancel:
            send_text_message(f"⚠️ Could not find '{target_code}' in today's routine. Check your spelling or try sending ROUTINE first.")
            return
            
        success_msg = f"{classes_to_cancel[0]['subject_name']} ({target_code}) has been"

    # 3. Lock them in the database as Cancelled
    for cls in classes_to_cancel:
        log_data = {
            "date": today_date,
            "subject_code": cls['subject_code'],
            "subject_name": cls['subject_name'],
            "status": "Cancelled",
            "is_locked": True
        }
        supabase.table("attendance_logs").upsert(log_data, on_conflict="date,subject_code").execute()

    # 4. Confirm with the user
    send_text_message(f"🛑 Done! {success_msg} pre-emptively marked as Cancelled. I won't bother you about it later.")

def handle_add_holiday(command_text):
    # Expected format: "Add Holiday YYYY-MM-DD Reason for holiday"
    parts = command_text.split(" ", 3)
    if len(parts) < 4:
        send_text_message("⚠️ Format incorrect. Please use: ADD HOLIDAY YYYY-MM-DD Reason")
        return
        
    date_str = parts[2]
    reason = parts[3]
    
    supabase.table("custom_events").upsert({
        "date": date_str,
        "reason": reason,
        "is_holiday": True
    }).execute()
    
    send_text_message(f"🌴 Holiday Added: {reason} on {date_str}. I will pause attendance for this day.")

def handle_remove_holiday(command_text):
    # Expected format: "REMOVE HOLIDAY YYYY-MM-DD"
    parts = command_text.split(" ")
    if len(parts) < 3:
        send_text_message("⚠️ Format incorrect. Please use: REMOVE HOLIDAY YYYY-MM-DD")
        return
        
    date_str = parts[2]
    
    # We set is_holiday to FALSE so it overrides any public holidays that day
    supabase.table("custom_events").upsert({
        "date": date_str,
        "reason": "College is Open",
        "is_holiday": False
    }).execute()
    
    send_text_message(f"✅ Holiday Removed: I will resume tracking classes for {date_str}.")

def handle_history(command_text):
    # Expected format: "HISTORY CS401"
    parts = command_text.split(" ")
    if len(parts) < 2:
        send_text_message("⚠️ Format incorrect. Please use: HISTORY [SUBJECT_CODE] (e.g., HISTORY CS401)")
        return

    target_code = parts[1]

    # Query database for days you were specifically 'Present'
    response = supabase.table("attendance_logs").select("date, subject_name").eq("subject_code", target_code).eq("status", "Present").order("date").execute()

    if not response.data:
        send_text_message(f"No 'Present' records found for {target_code}.")
        return

    subject_name = response.data[0]['subject_name']
    msg_text = f"📅 *Attendance History for {subject_name} ({target_code})*\n\n"
    msg_text += "You were Present on:\n"
    
    for log in response.data:
        msg_text += f"✅ {log['date']}\n"

    send_text_message(msg_text.strip())