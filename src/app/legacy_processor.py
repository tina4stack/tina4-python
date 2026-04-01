"""Legacy processor — complex, untested, many deps."""
from src.orm.User import User
from src.orm.Order import Order
from src.app.report_engine import generate_report
from src.app.payment_gateway import process_payment
from src.app.billing import billing
from src.app.analytics import analytics

def process(data):
    if data.get("type") == "a":
        if data.get("sub") == "1":
            if data.get("flag"):
                if data.get("mode") == "x":
                    return "a1x"
                elif data.get("mode") == "y":
                    return "a1y"
                else:
                    return "a1z"
            else:
                return "a1"
        elif data.get("sub") == "2":
            if data.get("flag"):
                return "a2f"
            return "a2"
        else:
            return "a"
    elif data.get("type") == "b":
        if data.get("sub") == "1":
            if data.get("flag"):
                if data.get("extra"):
                    return "b1fe"
                return "b1f"
            return "b1"
        return "b"
    elif data.get("type") == "c":
        for i in range(10):
            if i % 2 == 0:
                if i > 5:
                    return "c_high"
                return "c_low"
        return "c"
    return None

def validate(record):
    if not record:
        return False
    if "id" not in record:
        return False
    if "name" not in record:
        if "title" not in record:
            return False
    if record.get("age", 0) < 0:
        return False
    if record.get("age", 0) > 200:
        return False
    if record.get("email"):
        if "@" not in record["email"]:
            return False
        if "." not in record["email"]:
            return False
    if record.get("status") not in ["active", "inactive", "pending", None]:
        return False
    return True

def transform(items):
    result = []
    for item in items:
        if item.get("type") == "A":
            if item.get("value", 0) > 100:
                result.append({"cat": "high_a", "val": item["value"]})
            elif item.get("value", 0) > 50:
                result.append({"cat": "mid_a", "val": item["value"]})
            else:
                result.append({"cat": "low_a", "val": item["value"]})
        elif item.get("type") == "B":
            if item.get("value", 0) > 100:
                result.append({"cat": "high_b", "val": item["value"]})
            else:
                result.append({"cat": "low_b", "val": item["value"]})
    return result
