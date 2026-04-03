from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from whatsapp import ask_attendance
from database import supabase
import holidays

wb_holidays = holidays.IN(prov="WB")

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

def start_scheduler():
    scheduler = BackgroundScheduler()

    scheduler.add_job(check_routine_and_notify, 'interval', minutes=1)
    scheduler.start()