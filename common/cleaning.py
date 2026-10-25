"""Safai ke chhote helpers jo kai scripts istemal karengi."""
import re
from datetime import datetime


def clean_text(value):
    """Aage peeche aur beech ke faltu spaces hatao."""
    return re.sub(r"\s+", " ", value).strip()


def parse_date(value):
    """Teeno formats ko YYYY-MM-DD banao. Khali ho to None. Ajeeb format par ruk jao."""
    value = clean_text(value)
    if value == "":
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):  # DD/MM/YYYY
        return datetime.strptime(value, "%d/%m/%Y").strftime("%Y-%m-%d")
    if re.fullmatch(r"\d{2}-[A-Za-z]{3}-\d{4}", value):  # DD-Mon-YYYY
        return datetime.strptime(value, "%d-%b-%Y").strftime("%Y-%m-%d")
    raise ValueError(f"Ajeeb date format mila: {value!r}")