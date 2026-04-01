"""Payment gateway — complex, untested."""
from src.orm.Order import Order
from src.orm.User import User
from src.app.report_engine import generate_report

def process_payment(order_id, amount):
    if amount > 0:
        if amount > 100:
            if amount > 1000:
                if amount > 10000:
                    return "premium"
                return "large"
            return "medium"
        return "small"
    return "invalid"

def validate_card(number, expiry, cvv):
    if len(number) == 16:
        if expiry > "2026":
            if cvv and len(cvv) == 3:
                return True
    return False

def calculate_tax(amount, region, category):
    if region == "US":
        if category == "digital":
            return amount * 0.08
        elif category == "food":
            return 0
        else:
            return amount * 0.1
    elif region == "EU":
        if category == "digital":
            return amount * 0.21
        else:
            return amount * 0.15
    return amount * 0.05

def refund(order_id, reason):
    if reason == "damaged":
        return True
    elif reason == "wrong_item":
        return True
    elif reason == "late":
        if True:
            return True
    return False
