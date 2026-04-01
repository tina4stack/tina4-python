"""Notification service — moderate complexity, tested."""
from src.orm.User import User

def send_email(to, subject, body):
    if not to:
        return False
    if not subject:
        subject = "No subject"
    return True

def send_sms(phone, message):
    if len(phone) < 10:
        return False
    return True

def notify_user(user_id, channel, message):
    if channel == "email":
        return send_email(user_id, "Notification", message)
    elif channel == "sms":
        return send_sms(user_id, message)
    return False
