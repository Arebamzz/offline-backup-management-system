import datetime
import time


MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


def epoch_seconds(value=None):
    if value is None:
        return int(time.time())
    return int(value.timestamp())


def format_batch_label(value):
    return value.strftime("%Y-%m-%d_%H%M%S")


def format_log_date(value):
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def format_report_date(value):
    local_value = value.astimezone()
    return "{:02d} {} {} {:02d}:{:02d}:{:02d}".format(
        local_value.day,
        MONTHS[local_value.month - 1],
        local_value.year,
        local_value.hour,
        local_value.minute,
        local_value.second,
    )


def format_report_day(value):
    local_value = value.astimezone()
    return "{:02d} {} {}".format(
        local_value.day,
        MONTHS[local_value.month - 1],
        local_value.year,
    )


def human_duration(total_seconds):
    total = max(0, int(total_seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return "{}h {}m {}s".format(hours, minutes, seconds)


def now():
    return datetime.datetime.now().astimezone()
