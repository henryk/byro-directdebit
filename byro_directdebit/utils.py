from workalendar.registry import registry
from datetime import datetime, timedelta


def next_debit_date(target_days=14, start_date=None, region="DE"):
    cal = registry.get_calendar_class(region)()
    result = start_date or datetime.today()
    result = result + timedelta(days=target_days)
    result = cal.find_following_working_day(result)
    return result
