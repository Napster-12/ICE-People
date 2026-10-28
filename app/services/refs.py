"""Reference numbers like REQ-2026-00001, unique even when two users save at once."""
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import RefSequence
from app.services.dates import today

PREFIXES = {"REQ", "POS", "ADV", "OFR", "ONB", "SKA", "EXT"}


def next_reference(prefix, year=None):
    if prefix not in PREFIXES:
        raise ValueError(f"Unknown reference prefix {prefix}")
    year = year or today().year
    for _ in range(5):
        # An atomic UPDATE ... SET last = last + 1 locks the row, so concurrent
        # callers each get their own number.
        result = db.session.execute(
            update(RefSequence).where(RefSequence.prefix == prefix, RefSequence.year == year)
            .values(last=RefSequence.last + 1).returning(RefSequence.last))
        row = result.first()
        if row:
            return f"{prefix}-{year}-{row[0]:05d}"
        try:
            with db.session.begin_nested():
                db.session.add(RefSequence(prefix=prefix, year=year, last=0))
        except IntegrityError:
            pass  # another request created the row first; retry the UPDATE
    raise RuntimeError("Could not allocate a reference number")
