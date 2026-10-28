# Original recruitment portal (archived)

These files are the single-file portal as it was before it was merged into the HR Automation
System:

- `app.py`
- `ats.py`
- `seed_dummy.py`
- `templates/`
- `static/`

They are kept unchanged for reference. Every feature now lives in the main app:

| Old | New |
|---|---|
| Public routes in `app.py` | `app/recruitment/careers.py` |
| `/admin` routes in `app.py` | `app/recruitment/routes.py` (now `/recruitment/...`) |
| `ats.py` | `app/services/ats.py` (unchanged) |
| Admin login | `/login`, with roles and two-step verification |
| CVs stored as BLOBs in `portal.db` | Files in `instance/uploads` |

To copy the old data into the new system, run `flask import-legacy` from the project root. It reads
`../portal.db` and never changes it.

To run the old portal on its own, from the project root:

```
PORTAL_DB=portal.db python legacy/app.py
```
