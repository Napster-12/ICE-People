"""South African ID number validation (format, date of birth and Luhn checksum)."""
import re
from datetime import date


def luhn_ok(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def sa_id_birth_date(id_number, today=None):
    today = today or date.today()
    yy, mm, dd = int(id_number[0:2]), int(id_number[2:4]), int(id_number[4:6])
    century = 2000 if 2000 + yy <= today.year else 1900
    return date(century + yy, mm, dd)


def validate_sa_id(id_number, date_of_birth=None):
    """Returns a list of problems (empty when valid)."""
    id_number = (id_number or "").replace(" ", "")
    if not re.fullmatch(r"\d{13}", id_number):
        return ["An SA ID number has 13 digits."]
    problems = []
    try:
        born = sa_id_birth_date(id_number)
    except ValueError:
        return ["The first six digits of the ID number aren't a valid date of birth."]
    if id_number[10] not in "01":
        problems.append("The citizenship digit (11th) must be 0 or 1.")
    if not luhn_ok(id_number):
        problems.append("The ID number's check digit is wrong.")
    if date_of_birth and born != date_of_birth:
        problems.append("The ID number doesn't match the date of birth.")
    return problems
