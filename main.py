import os
import math
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
from dotenv import load_dotenv
from database import supabase
from whatsapp import send_text_message, send_interactive_menu, send_update_question, send_dynamic_absent_list
from scheduler import start_scheduler, is_today_a_holiday
from typing import List

load_dotenv()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

# ==========================================
# PYDANTIC MODELS (For Web Dashboard)
# ==========================================
class ClassItem(BaseModel):
    day_of_week: str
    subject_code: str
    subject_name: str
    start_time: str
    end_time: str

class SyncRoutinePayload(BaseModel):
    phone_number: str
    classes: List[ClassItem]

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield

app = FastAPI(lifespan=lifespan)

# ==========================================
# WEB DASHBOARD ROUTES
# ==========================================
@app.get("/")
def home():
    return {"status": "EchoRoll is running!"}

@app.get("/dashboard")
def serve_dashboard():
    # Serves the HTML file for users to input their schedule
    return FileResponse("public/dashboard.html")

@app.post("/api/sync-routine")
async def sync_routine(payload: SyncRoutinePayload):
    try:
        phone = payload.phone_number
        
        # 1. Delete the user's old routine so we don't get duplicates when they update
        supabase.table("routine").delete().eq("phone_number", phone).execute()
        
        # 2. Format the new classes for Supabase
        records_to_insert = []
        for cls in payload.classes:
            records_to_insert.append({
                "phone_number": phone,
                "day_of_week": cls.day_of_week,
                "subject_code": cls.subject_code,
                "subject_name": cls.subject_name,
                "start_time": f"{cls.start_time}:00" if len(cls.start_time) == 5 else cls.start_time,
                "end_time": f"{cls.end_time}:00" if len(cls.end_time) == 5 else cls.end_time
            })
            
        # 3. Bulk insert the new routine
        if records_to_insert:
            supabase.table("routine").insert(records_to_insert).execute()
            
        return {"status": "success", "message": f"Successfully synced {len(records_to_insert)} classes!"}
        
    except Exception as e:
        print(f"Database Error: {e}")
        return Response(content="Failed to sync routine", status_code=500)

# ==========================================
# WHATSAPP WEBHOOK ROUTES
# ==========================================
@app.get("/webhook")
def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified!")
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Verification failed", status_code=403)

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
            # MULTI-TENANT: Extract the sender's phone number!
            sender_number = msg["from"]
            today_date = datetime.now().strftime("%Y-%m-%d")
            
            # ==========================================
            # 1. HANDLE PLAIN TEXT MESSAGES
            # ==========================================
            if msg.get("type") == "text":
                text = msg["text"]["body"].strip().upper()
                raw_text = msg["text"]["body"].strip()
                print(f"Bot received text: {text} from {sender_number}")
                
                if text == "HI": send_interactive_menu(sender_number)
                elif text == "ROUTINE": handle_routine(sender_number)
                elif text == "PERCENTAGE": handle_percentage(sender_number)
                elif text == "TARGET": handle_target(sender_number)
                elif text == "ABSENT": handle_absent_menu(sender_number)
                elif text == "ABSENT ALL": handle_mass_absent(sender_number)
                elif text.startswith("CANCEL"): handle_cancel(text, sender_number)
                elif text.startswith("ADD HOLIDAY"): handle_add_holiday(raw_text, sender_number)
                elif text.startswith("REMOVE HOLIDAY"): handle_remove_holiday(text, sender_number)
                elif text.startswith("HISTORY"): handle_history(text, sender_number)

            # ==========================================
            # 2. HANDLE INTERACTIVE BUTTON/LIST CLICKS
            # ==========================================
            elif msg.get("type") == "interactive":
                interactive_obj = msg["interactive"]
                
                if "list_reply" in interactive_obj:
                    button_id = interactive_obj["list_reply"]["id"]
                elif "button_reply" in interactive_obj:
                    button_id = interactive_obj["button_reply"]["id"]
                else:
                    return {"status": "ignored"}

                # --- A. Menu Buttons ---
                if button_id.startswith("menu_"):
                    if button_id == "menu_routine": handle_routine(sender_number)
                    elif button_id == "menu_percentage": handle_percentage(sender_number)
                    elif button_id == "menu_target": handle_target(sender_number)

                # --- B. Selective Absent Clicks ---
                elif button_id.startswith("bulk_absent_"):
                    subject_code = button_id.replace("bulk_absent_", "")
                    
                    routine = supabase.table("routine").select("subject_name")\
                        .eq("subject_code", subject_code)\
                        .eq("phone_number", sender_number).execute()
                    
                    sub_name = routine.data[0]['subject_name'] if routine.data else "Subject"

                    log_data = {
                        "date": today_date,
                        "subject_code": subject_code,
                        "subject_name": sub_name,
                        "status": "Absent",
                        "is_locked": True,
                        "phone_number": sender_number
                    }
                    # Note the updated on_conflict to include phone_number
                    supabase.table("attendance_logs").upsert(log_data, on_conflict="date,subject_code,phone_number").execute()
                    
                    send_text_message(f"✅ Marked *{subject_code}* as Absent.\n\n_Tap another subject from the menu above if you missed others._", sender_number)

                # --- C. The "Update?" Question Logic ---
                elif button_id.startswith("lock_"):
                    action, subject_code = button_id.replace("lock_", "").split("_")
                    
                    if action == "yes":
                        supabase.table("attendance_logs").update({"is_locked": False})\
                            .eq("date", today_date)\
                            .eq("subject_code", subject_code)\
                            .eq("phone_number", sender_number).execute()
                        send_text_message(f"🔓 Attendance for {subject_code} is now unlocked. You can use the previous buttons to change it.", sender_number)
                    else:
                        send_text_message(f"✅ Attendance for {subject_code} finalized.", sender_number)

                # --- D. Attendance Marking Logic ---
                elif button_id.startswith(("present_", "absent_", "cancelled_")):
                    status, subject_code, subject_name = button_id.split("_", 2)

                    existing = supabase.table("attendance_logs").select("is_locked")\
                        .eq("date", today_date)\
                        .eq("subject_code", subject_code)\
                        .eq("phone_number", sender_number).execute()
                    
                    if existing.data and existing.data[0].get('is_locked') == True:
                        print(f"Ignored click: {subject_code} is locked for {sender_number}.")
                        return {"status": "ignored"}

                    log_data = {
                        "date": today_date,
                        "subject_code": subject_code,
                        "subject_name": subject_name,
                        "status": status.capitalize(),
                        "is_locked": True,
                        "phone_number": sender_number
                    }

                    supabase.table("attendance_logs").upsert(log_data, on_conflict="date,subject_code,phone_number").execute()
                    
                    send_text_message(f"📝 Logged! Marked as {status.capitalize()} for {subject_name} ({subject_code}).", sender_number)
                    send_update_question(subject_code, subject_name, sender_number)

    except Exception as e:
        print(f"Error processing webhook: {e}")

    return {"status": "success"}


# ==========================================
# HELPER FUNCTIONS (Now Multi-Tenant Enabled)
# ==========================================

def handle_routine(sender_number):
    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    current_day = now.strftime("%A")

    if is_today_a_holiday(today_date, sender_number):
        send_text_message("🌴 It's a holiday today! Chill out and enjoy your day off. 🎮🍿", sender_number)
        return

    response = supabase.table("routine").select("*")\
        .eq("day_of_week", current_day)\
        .eq("phone_number", sender_number)\
        .order("start_time").execute()
    
    classes = response.data
    if not classes:
        send_text_message(f"No classes scheduled for today ({current_day})! Enjoy your day off. 🎉", sender_number)
        return

    msg_text = f"📅 *Routine for {current_day}*\n\n"
    for cls in classes:
        prof = cls.get('professor_name') or "TBA"
        msg_text += f"🔹 *{cls['subject_name']}* ({cls['subject_code']})\n"
        msg_text += f"⏰ {cls['start_time']} - {cls['end_time']}\n"
        msg_text += f"👨‍🏫 Prof: {prof}\n\n"
        
    send_text_message(msg_text.strip(), sender_number)

def get_attendance_data(sender_number):
    response = supabase.table("attendance_logs").select("*")\
        .eq("phone_number", sender_number).execute()
    logs = response.data
    
    subjects = {}
    for log in logs:
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

def handle_percentage(sender_number):
    subjects = get_attendance_data(sender_number)
    
    if not subjects:
        send_text_message("No attendance records found yet!", sender_number)
        return
        
    msg_text = "📊 *Current Attendance Percentage*\n\n"
    for code, data in subjects.items():
        total = data['present'] + data['absent']
        if total == 0:
            continue
            
        percent = (data['present'] / total) * 100
        msg_text += f"🔹 *{data['name']}* ({code})\n"
        msg_text += f"📈 {round(percent, 2)}% ({data['present']}/{total} classes)\n\n"
        
    send_text_message(msg_text.strip(), sender_number)

def handle_target(sender_number):
    subjects = get_attendance_data(sender_number)
    
    if not subjects:
        send_text_message("No attendance records found yet!", sender_number)
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

    send_text_message(msg_text.strip(), sender_number)

def handle_cancel(command_text, sender_number):
    today_date = datetime.now().strftime("%Y-%m-%d")
    current_day = datetime.now().strftime("%A")
    
    routine = supabase.table("routine").select("*")\
        .eq("day_of_week", current_day)\
        .eq("phone_number", sender_number).execute()
        
    if not routine.data:
        send_text_message("You don't have any classes to cancel today!", sender_number)
        return

    classes_to_cancel = []
    
    if command_text == "CANCEL ALL":
        classes_to_cancel = routine.data
        success_msg = "All classes for today have been"
    else:
        target_code = command_text.replace("CANCEL ", "").strip()
        for cls in routine.data:
            if cls['subject_code'] == target_code:
                classes_to_cancel.append(cls)
                
        if not classes_to_cancel:
            send_text_message(f"⚠️ Could not find '{target_code}' in today's routine.", sender_number)
            return
        success_msg = f"{classes_to_cancel[0]['subject_name']} ({target_code}) has been"

    for cls in classes_to_cancel:
        log_data = {
            "date": today_date,
            "subject_code": cls['subject_code'],
            "subject_name": cls['subject_name'],
            "status": "Cancelled",
            "is_locked": True,
            "phone_number": sender_number
        }
        supabase.table("attendance_logs").upsert(log_data, on_conflict="date,subject_code,phone_number").execute()

    send_text_message(f"🛑 Done! {success_msg} pre-emptively marked as Cancelled.", sender_number)

def handle_add_holiday(command_text, sender_number):
    parts = command_text.split(" ", 3)
    if len(parts) < 4:
        send_text_message("⚠️ Format incorrect. Please use: ADD HOLIDAY YYYY-MM-DD Reason", sender_number)
        return
        
    date_str = parts[2]
    reason = parts[3]
    
    supabase.table("custom_events").insert({
        "date": date_str,
        "reason": reason,
        "is_holiday": True,
        "phone_number": sender_number
    }).execute()
    
    send_text_message(f"🌴 Holiday Added: {reason} on {date_str}. I will pause attendance for this day.", sender_number)

def handle_remove_holiday(command_text, sender_number):
    parts = command_text.split(" ")
    if len(parts) < 3:
        send_text_message("⚠️ Format incorrect. Please use: REMOVE HOLIDAY YYYY-MM-DD", sender_number)
        return
        
    date_str = parts[2]
    
    supabase.table("custom_events").insert({
        "date": date_str,
        "reason": "College is Open",
        "is_holiday": False,
        "phone_number": sender_number
    }).execute()
    
    send_text_message(f"✅ Holiday Removed: I will resume tracking classes for {date_str}.", sender_number)

def handle_history(command_text, sender_number):
    parts = command_text.split(" ")
    if len(parts) < 2:
        send_text_message("⚠️ Format incorrect. Please use: HISTORY [SUBJECT_CODE]", sender_number)
        return

    target_code = parts[1]
    
    response = supabase.table("attendance_logs").select("date, subject_name")\
        .eq("subject_code", target_code)\
        .eq("status", "Present")\
        .eq("phone_number", sender_number)\
        .order("date").execute()

    if not response.data:
        send_text_message(f"No 'Present' records found for {target_code}.", sender_number)
        return

    subject_name = response.data[0]['subject_name']
    msg_text = f"📅 *Attendance History for {subject_name} ({target_code})*\n\n"
    msg_text += "You were Present on:\n"
    
    for log in response.data:
        msg_text += f"✅ {log['date']}\n"

    send_text_message(msg_text.strip(), sender_number)

def handle_absent_menu(sender_number):
    current_day = datetime.now().strftime("%A")
    routine = supabase.table("routine").select("*")\
        .eq("day_of_week", current_day)\
        .eq("phone_number", sender_number).execute()
    
    if not routine.data:
        send_text_message("You don't have any classes to miss today!", sender_number)
        return
        
    send_dynamic_absent_list(routine.data, current_day, sender_number)

def handle_mass_absent(sender_number):
    today_date = datetime.now().strftime("%Y-%m-%d")
    current_day = datetime.now().strftime("%A")
    
    routine = supabase.table("routine").select("*")\
        .eq("day_of_week", current_day)\
        .eq("phone_number", sender_number).execute()
    
    if not routine.data:
        send_text_message("You don't have any classes to miss today!", sender_number)
        return

    for cls in routine.data:
        log_data = {
            "date": today_date,
            "subject_code": cls['subject_code'],
            "subject_name": cls['subject_name'],
            "status": "Absent",
            "is_locked": True,
            "phone_number": sender_number
        }
        supabase.table("attendance_logs").upsert(log_data, on_conflict="date,subject_code,phone_number").execute()

    send_text_message("🛌 Done! All classes for today have been marked as Absent. Get some rest!", sender_number)