import holidays
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from database import supabase
from whatsapp import ask_attendance, send_text_message

wb_holidays = holidays.IN(prov="WB")

def is_today_a_holiday(today_date, phone_number):
    """Checks custom events per user, then falls back to public holidays."""
    override_check = supabase.table("custom_events").select("*")\
        .eq("date", today_date)\
        .eq("phone_number", phone_number)\
        .execute()
    
    if override_check.data:
        is_holiday = override_check.data[0]['is_holiday']
        reason = override_check.data[0]['reason']
        
        if is_holiday:
            print(f"[{phone_number}] Bot resting today (Custom Event): {reason}")
            return True
        else:
            print(f"[{phone_number}] Override detected: College is open today.")
            return False 
            
    elif today_date in wb_holidays:
        official_reason = wb_holidays.get(today_date)
        print(f"[{phone_number}] Bot resting today (Public Holiday): {official_reason}")
        return True
        
    return False

def check_schedule():
    """Runs every minute: Finds ALL classes ending right now for ALL users."""
    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    current_day = now.strftime("%A")
    current_time = now.strftime("%H:%M:00")
    
    # 1. Query Supabase for ANY class that matches today's day AND ends at this exact minute
    response = supabase.table("routine").select("*")\
        .eq("day_of_week", current_day)\
        .eq("end_time", current_time)\
        .execute()

    classes = response.data
    if not classes:
        return

    # 2. Loop through the list and process each student independently
    for cls in classes:
        user_phone = cls['phone_number']
        sub_code = cls['subject_code']
        sub_name = cls['subject_name']

        # 3. Check if THIS specific user has a holiday
        if is_today_a_holiday(today_date, user_phone):
            continue 
            
        # 4. Check if THIS specific user already logged attendance (e.g., via ABSENT ALL)
        existing_log = supabase.table("attendance_logs").select("status")\
            .eq("date", today_date)\
            .eq("subject_code", sub_code)\
            .eq("phone_number", user_phone)\
            .execute()
            
        if existing_log.data:
            print(f"[{user_phone}] Skipping {sub_code} - already marked as {existing_log.data[0]['status']}")
            continue 
            
        # 5. Dispatch the WhatsApp message to this specific user
        ask_attendance(sub_name, sub_code, user_phone)

def morning_danger_check():
    """Runs at 8:00 AM: Checks streaks and percentages for ALL users with classes today."""
    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    current_day = now.strftime("%A")

    # 1. Get ALL classes happening today across the entire database
    response = supabase.table("routine").select("*").eq("day_of_week", current_day).execute()
    classes = response.data
    
    if not classes: 
        return

    # 2. Loop through every single class happening today
    for cls in classes:
        user_phone = cls['phone_number']
        sub_code = cls['subject_code']
        sub_name = cls['subject_name']

        # 3. Skip warnings if THIS user has a holiday
        if is_today_a_holiday(today_date, user_phone):
            continue 

        # 4. Get past logs for THIS user and THIS subject
        logs = supabase.table("attendance_logs").select("status")\
            .eq("subject_code", sub_code)\
            .eq("phone_number", user_phone)\
            .neq("status", "Cancelled")\
            .order("date", desc=True)\
            .execute()

        if not logs.data: 
            continue
        
        total_classes = len(logs.data)
        present_classes = sum(1 for log in logs.data if log['status'] == 'Present')
        percentage = (present_classes / total_classes) * 100 if total_classes > 0 else 100

        # 5. Check if THIS user missed the last 3 in a row
        missed_last_3 = False
        if total_classes >= 3:
            last_3_statuses = [log['status'] for log in logs.data[:3]]
            if last_3_statuses == ['Absent', 'Absent', 'Absent']:
                missed_last_3 = True

        # 6. Determine if a warning is needed
        warning_msg = None
        if percentage < 50:
            warning_msg = f"📉 Your overall attendance is dangerously low ({round(percentage, 2)}%)."
        elif missed_last_3:
            warning_msg = "⚠️ You have missed the last 3 classes in a row."

        # 7. Dispatch the warning directly to their phone
        if warning_msg:
            msg = f"🚨 *DANGER ZONE ALERT* 🚨\n\n"
            msg += f"You have *{sub_name}* today at {cls['start_time']}.\n"
            msg += f"{warning_msg}\n\n"
            msg += "Do not miss this class!"
            
            send_text_message(msg, user_phone)

def start_scheduler():
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    
    scheduler.add_job(check_schedule, 'cron', minute="*")
    scheduler.add_job(morning_danger_check, 'cron', hour=8, minute=0)
    
    scheduler.start()
    print(f"Scheduler started in {datetime.now()}!")