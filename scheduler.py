from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from whatsapp import ask_attendance
from database import supabase

def check_routine_and_notify():
    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    current_day = now.strftime("%A")
    current_time = now.strftime("%H:%M:00")

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