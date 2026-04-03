from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from whatsapp import ask_attendance, send_text_message
from database import supabase
import holidays

wb_holidays = holidays.IN(prov="WB")

def is_today_a_holiday(today_date):
    """Helper function to check both custom overrides and public holidays."""
    override_check = supabase.table("custom_events").select("*").eq("date", today_date).execute()
    
    if override_check.data:
        is_holiday = override_check.data[0]['is_holiday']
        reason = override_check.data[0]['reason']
        
        if is_holiday:
            print(f"Bot resting today (Custom Event): {reason}")
            return True
        else:
            print(f"Override detected: College is open today despite any public holidays.")
            return False  # Force the bot to stay awake
            
    elif today_date in wb_holidays:
        official_reason = wb_holidays.get(today_date)
        print(f"Bot resting today (Public Holiday): {official_reason}")
        return True
        
    return False

def check_routine_and_notify():
    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    current_day = now.strftime("%A")
    current_time = now.strftime("%H:%M:00")

    override_check = supabase.table("custom_events").select("*").eq("date", today_date).execute()

    if override_check.data:
        is_holiday = override_check.data[0]['is_holiday']
        reason = override_check.data[0]['reason']
        
        if is_holiday:
            print(f"Bot resting today (Custom Event): {reason}")
            return # Pauses the bot
        else:
            print(f"Override detected: College is open today despite any public holidays.")
            # Do NOT return, let the bot continue to the class checks
            
    # 2. If no custom override, check the automatic public holiday calendar
    elif today_date in wb_holidays:
        official_reason = wb_holidays.get(today_date)
        print(f"Bot resting today (Public Holiday): {official_reason}")
        return

    response = supabase.table("routine").select("*").eq("day_of_week", current_day).eq("end_time", current_time).execute()

    classes_ended = response.data
    for cls in classes_ended:
        # Check if this specific class was ALREADY logged today
        existing_log = supabase.table("attendance_logs").select("status").eq("date", today_date).eq("subject_code", cls['subject_code']).execute()
            
        if existing_log.data:
            # If data exists, it means you already marked it (e.g., via CANCEL ALL)
            print(f"Skipping {cls['subject_code']} - already marked as {existing_log.data[0]['status']}")
            continue # Skips to the next class, no message sent!
            
        # If no data exists, ask the user normally
        ask_attendance(cls['subject_name'], cls['subject_code'])

def morning_danger_check():
    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    current_day = now.strftime("%A")

    # 1. Skip if today is a holiday (You can reuse your holiday logic here)
    if today_date in wb_holidays:
        return 

    # 2. Get today's classes
    routine = supabase.table("routine").select("*").eq("day_of_week", current_day).execute()
    if not routine.data: return

    for cls in routine.data:
        sub_code = cls['subject_code']
        sub_name = cls['subject_name']

        # 3. Get all past logs for this subject, ignoring cancelled classes, ordered from newest to oldest
        logs = supabase.table("attendance_logs")\
            .select("status")\
            .eq("subject_code", sub_code)\
            .neq("status", "Cancelled")\
            .order("date", desc=True)\
            .execute()

        if not logs.data: continue
        
        total_classes = len(logs.data)
        present_classes = sum(1 for log in logs.data if log['status'] == 'Present')
        percentage = (present_classes / total_classes) * 100 if total_classes > 0 else 100

        # 4. Check if you missed the last 3 in a row
        missed_last_3 = False
        if total_classes >= 3:
            last_3_statuses = [log['status'] for log in logs.data[:3]]
            if last_3_statuses == ['Absent', 'Absent', 'Absent']:
                missed_last_3 = True

        # 5. Send warning if conditions are met
        warning_msg = None
        if percentage < 50:
            warning_msg = f"📉 Your overall attendance is dangerously low ({round(percentage, 2)}%)."
        elif missed_last_3:
            warning_msg = "⚠️ You have missed the last 3 classes in a row."

        if warning_msg:
            msg = f"🚨 *DANGER ZONE ALERT* 🚨\n\n"
            msg += f"You have *{sub_name}* today at {cls['start_time']}.\n"
            msg += f"{warning_msg}\n\n"
            msg += "Do not miss this class!"
            
            send_text_message(msg)

def start_scheduler():
    scheduler = BackgroundScheduler()

    scheduler.add_job(check_routine_and_notify, 'interval', minutes=1)
    scheduler.start()