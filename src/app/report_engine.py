"""Report engine with intentionally high complexity for metrics demo."""

def generate_report(report_type, data, options=None):
    """This function has high cyclomatic complexity on purpose."""
    options = options or {}
    output_format = options.get("format", "html")
    include_charts = options.get("charts", False)
    include_summary = options.get("summary", True)
    date_range = options.get("date_range", "month")
    group_by = options.get("group_by", "day")
    currency = options.get("currency", "USD")
    locale = options.get("locale", "en")
    
    if report_type == "sales":
        if date_range == "day":
            rows = _daily_sales(data)
        elif date_range == "week":
            rows = _weekly_sales(data)
        elif date_range == "month":
            rows = _monthly_sales(data)
        elif date_range == "quarter":
            rows = _quarterly_sales(data)
        elif date_range == "year":
            rows = _yearly_sales(data)
        else:
            rows = data
            
        if group_by == "category":
            rows = _group_by_category(rows)
        elif group_by == "region":
            rows = _group_by_region(rows)
        elif group_by == "product":
            rows = _group_by_product(rows)
        elif group_by == "customer":
            rows = _group_by_customer(rows)
            
    elif report_type == "inventory":
        if options.get("low_stock_only"):
            rows = [r for r in data if r.get("qty", 0) < r.get("reorder_point", 10)]
        elif options.get("overstock_only"):
            rows = [r for r in data if r.get("qty", 0) > r.get("max_stock", 100)]
        else:
            rows = data
            
        if options.get("include_value"):
            for row in rows:
                row["value"] = row.get("qty", 0) * row.get("unit_cost", 0)
                if currency != "USD":
                    row["value"] = _convert_currency(row["value"], "USD", currency)
                    
    elif report_type == "customers":
        if options.get("active_only"):
            rows = [r for r in data if r.get("active")]
        elif options.get("churned_only"):
            rows = [r for r in data if not r.get("active") and r.get("was_active")]
        else:
            rows = data
            
        if options.get("with_orders"):
            for row in rows:
                row["order_count"] = _count_orders(row["id"])
                row["total_spend"] = _total_spend(row["id"])
                if row["total_spend"] > 10000:
                    row["tier"] = "platinum"
                elif row["total_spend"] > 5000:
                    row["tier"] = "gold"
                elif row["total_spend"] > 1000:
                    row["tier"] = "silver"
                else:
                    row["tier"] = "bronze"
    else:
        rows = data
    
    # Format output
    if output_format == "html":
        result = _render_html_table(rows, include_charts, include_summary)
    elif output_format == "csv":
        result = _render_csv(rows)
    elif output_format == "pdf":
        result = _render_pdf(rows, include_charts, include_summary)
    elif output_format == "excel":
        result = _render_excel(rows, include_charts)
    elif output_format == "json":
        result = {"rows": rows, "count": len(rows)}
    else:
        result = str(rows)
    
    return result

def _daily_sales(data): return data
def _weekly_sales(data): return data
def _monthly_sales(data): return data
def _quarterly_sales(data): return data
def _yearly_sales(data): return data
def _group_by_category(rows): return rows
def _group_by_region(rows): return rows
def _group_by_product(rows): return rows
def _group_by_customer(rows): return rows
def _convert_currency(amount, from_c, to_c): return amount
def _count_orders(cid): return 0
def _total_spend(cid): return 0
def _render_html_table(rows, charts, summary): return "<table></table>"
def _render_csv(rows): return ""
def _render_pdf(rows, charts, summary): return b""
def _render_excel(rows, charts): return b""


class DataProcessor:
    """A class with several methods of varying complexity."""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.cache = {}
        self.errors = []
    
    def validate_record(self, record):
        """Medium complexity validation."""
        errors = []
        if not record.get("id"):
            errors.append("Missing ID")
        if not record.get("name") or len(record["name"]) < 2:
            errors.append("Name too short")
        if record.get("email") and "@" not in record["email"]:
            errors.append("Invalid email")
        if record.get("age") and (record["age"] < 0 or record["age"] > 150):
            errors.append("Invalid age")
        if record.get("phone"):
            phone = record["phone"].replace(" ", "").replace("-", "")
            if not phone.startswith("+") and not phone.isdigit():
                errors.append("Invalid phone")
            elif len(phone) < 7 or len(phone) > 15:
                errors.append("Phone length invalid")
        if record.get("address"):
            addr = record["address"]
            if not addr.get("street") or not addr.get("city"):
                errors.append("Incomplete address")
            if addr.get("zip") and not addr["zip"].replace("-", "").isdigit():
                errors.append("Invalid zip")
        return errors
    
    def transform(self, records, rules):
        """Apply transformation rules to records."""
        result = []
        for record in records:
            transformed = dict(record)
            for rule in rules:
                field = rule.get("field")
                action = rule.get("action")
                if not field or not action:
                    continue
                if action == "upper" and field in transformed:
                    transformed[field] = str(transformed[field]).upper()
                elif action == "lower" and field in transformed:
                    transformed[field] = str(transformed[field]).lower()
                elif action == "trim" and field in transformed:
                    transformed[field] = str(transformed[field]).strip()
                elif action == "default" and field not in transformed:
                    transformed[field] = rule.get("value", "")
                elif action == "rename":
                    new_name = rule.get("to")
                    if new_name and field in transformed:
                        transformed[new_name] = transformed.pop(field)
                elif action == "delete" and field in transformed:
                    del transformed[field]
                elif action == "compute":
                    expr = rule.get("expr", "")
                    try:
                        transformed[field] = eval(expr, {"r": transformed})
                    except Exception:
                        pass
            result.append(transformed)
        return result
    
    def aggregate(self, records, group_field, agg_field, agg_func="sum"):
        """Group and aggregate records."""
        groups = {}
        for record in records:
            key = record.get(group_field, "unknown")
            if key not in groups:
                groups[key] = []
            groups[key].append(record.get(agg_field, 0))
        
        result = {}
        for key, values in groups.items():
            if agg_func == "sum":
                result[key] = sum(values)
            elif agg_func == "avg":
                result[key] = sum(values) / len(values) if values else 0
            elif agg_func == "min":
                result[key] = min(values) if values else 0
            elif agg_func == "max":
                result[key] = max(values) if values else 0
            elif agg_func == "count":
                result[key] = len(values)
            else:
                result[key] = values
        return result
