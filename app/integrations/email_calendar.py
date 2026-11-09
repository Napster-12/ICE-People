"""Email / calendar (Outlook). The mock writes emails to the log/console; SmtpEmailCalendar sends real email."""
import logging
import secrets
import smtplib
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from flask import current_app

from app.integrations.base import Adapter, IntegrationError

log = logging.getLogger("email")

# Live email is sent in the background (8 Nov 2026, at the user's request: pages waited seconds for Gmail). Two
# workers, so a batch of emails doesn't open dozens of SMTP connections at once. EMAIL_ASYNC = False sends in the
# request instead (tests and the send-test-email command, which reports the result).
_outbox = ThreadPoolExecutor(max_workers=2, thread_name_prefix="email")
_pending = []


def wait_for_emails(timeout=60):
    """Block until the emails queued so far are sent (tests, and CLI commands that want to report)."""
    while _pending:
        _pending.pop().result(timeout=timeout)


class EmailCalendarInterface(ABC):
    @abstractmethod
    def send_email(self, to, subject, body, html=None, attachments=None): ...
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

    def send_email(self, to, subject, body, html=None, attachments=None):
        def send():
            log.info("EMAIL to=%s subject=%s attachments=%s\n%s", to, subject,
                     [a[0] for a in attachments or []], body)
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


class SmtpEmailCalendar(MockEmailCalendar):
    """Real email over SMTP with STARTTLS, using IGSP's settings (6 Nov 2026). Every email is also sent, as a hidden
    copy (BCC), to EMAIL_COPY_TO for review. Calendar invites are still built here as .ics files (create_event)."""
    system = "email"

    def send_email(self, to, subject, body, html=None, attachments=None):
        """body is the plain-text version; html (emails.html_for) the designed one, with its images inline.
        attachments: [(filename, bytes, mime type)], e.g. the offer letter PDF."""
        from app.services.emails import inline_images
        cfg = current_app.config
        copies = [a.strip() for a in (cfg.get("EMAIL_COPY_TO") or "").split(",") if a.strip()]
        recipients = [to] + [c for c in copies if c.lower() != to.lower()]

        # The message is built now, in the request; only the SMTP conversation happens in the background.
        msg = None
        if cfg.get("SMTP_FROM"):
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = formataddr((cfg.get("SMTP_FROM_NAME") or "", cfg["SMTP_FROM"]))
            msg["To"] = to
            msg["Message-ID"] = make_msgid(domain=cfg["SMTP_FROM"].split("@")[-1])
            msg.set_content(body)
            if html:
                msg.add_alternative(html, subtype="html")
                html_part = msg.get_payload()[1]
                for cid, data, subtype in inline_images(html):
                    # inline, not attachment (8 Nov 2026): with the footer's banner and icons, mail apps listed the
                    # images as attachments and some showed the message unstyled.
                    html_part.add_related(data, "image", subtype, cid=f"<{cid}>", filename=f"{cid}.{subtype}",
                                          disposition="inline")
            for filename, data, mime in attachments or []:
                maintype, _, subtype = (mime or "application/octet-stream").partition("/")
                msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
        payload = {"to": to, "subject": subject, "bcc": copies[:5],
                   "attachments": [a[0] for a in attachments or []]}

        def send():
            if not (msg and cfg.get("SMTP_USER") and cfg.get("SMTP_PASSWORD")):
                raise RuntimeError("SMTP isn't configured: set SMTP_USER, SMTP_PASSWORD and SMTP_FROM in .env.")
            with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=20) as server:
                server.starttls()
                server.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
                server.send_message(msg, to_addrs=recipients)   # the copy is a BCC: not in the headers
            return {"status": "sent", "message_id": msg["Message-ID"]}

        if not cfg.get("EMAIL_ASYNC"):
            return self.call("send_email", payload, send)
        app = current_app._get_current_object()

        def in_background():
            from app.extensions import db
            with app.app_context():
                try:
                    self.call("send_email", payload, send)      # retries, and logs each attempt
                except IntegrationError as exc:
                    log.error("Email to %s failed: %s", to, exc)
                finally:
                    db.session.commit()
                    db.session.remove()

        _pending[:] = [f for f in _pending if not f.done()]
        _pending.append(_outbox.submit(in_background))
        return {"status": "queued", "message_id": msg["Message-ID"] if msg else None}
