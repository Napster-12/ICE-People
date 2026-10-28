"""Email / calendar (Outlook). The mock writes emails to the log/console."""
import logging
import secrets
from abc import ABC, abstractmethod
from datetime import timedelta

from flask import current_app

from app.integrations.base import Adapter

log = logging.getLogger("email")


class EmailCalendarInterface(ABC):
    @abstractmethod
    def send_email(self, to, subject, body): ...
    @abstractmethod
    def create_event(self, title, start, duration_minutes, attendees, location=""): ...


def build_ics(title, start, duration_minutes, attendees, location="", uid=None):
    """A minimal iCalendar invite (times in SAST)."""
    end = start + timedelta(minutes=duration_minutes)
    fmt = "%Y%m%dT%H%M%S"
    uid = uid or f"{secrets.token_hex(8)}@icebolethu.co.za"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Icebolethu Group//HR//EN", "METHOD:REQUEST",
             "BEGIN:VEVENT", f"UID:{uid}", f"DTSTART;TZID=Africa/Johannesburg:{start.strftime(fmt)}",
             f"DTEND;TZID=Africa/Johannesburg:{end.strftime(fmt)}", f"SUMMARY:{title}",
             f"LOCATION:{location}"]
    lines += [f"ATTENDEE;RSVP=TRUE:mailto:{a}" for a in attendees]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


class MockEmailCalendar(Adapter, EmailCalendarInterface):
    system = "email"

    def send_email(self, to, subject, body):
        def send():
            log.info("EMAIL to=%s subject=%s\n%s", to, subject, body)
            if current_app.config.get("MOCK_EMAIL_ECHO", True):
                print(f"\n----- EMAIL -----\nTo: {to}\nSubject: {subject}\n\n{body}\n-----------------")
            return {"status": "sent"}
        return self.call("send_email", {"to": to, "subject": subject}, send)

    def create_event(self, title, start, duration_minutes, attendees, location=""):
        def create():
            link = f"https://meet.example.invalid/{secrets.token_urlsafe(8)}"
            return {"ics": build_ics(title, start, duration_minutes, attendees, location or link),
                    "video_link": link}
        return self.call("create_event", {"title": title, "start": str(start), "attendees": attendees}, create)
