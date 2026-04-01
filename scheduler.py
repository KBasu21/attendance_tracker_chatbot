from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from whatsapp import ask_attendance
from database import supabase

def check_routine_and_notify():
    now = datetime.now()
    current_day = now.strftime("%A")
    current_time = now.strftime("%H:%M:00")

    response = supabase.table("routine").select("*").eq("day_of_week", current_day).eq("end_time", current_time).execute()

    classed_ended = response.data
    for cls in classed_ended:
        ask_attendance(cls['subject_name'], cls['subject_code'])
        print(f"triggered message for {cls['subject_name']}")

def start_scheduler():
    scheduler = BackgroundScheduler()

    scheduler.add_job(check_routine_and_notify, 'interval', minutes=1)
    scheduler.start()