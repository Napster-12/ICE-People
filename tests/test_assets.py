"""ICT asset register."""
from app.extensions import db
from app.models import Asset, AuditLog
from tests.conftest import login, user


def _issue(client, **overrides):
    data = {"asset_tag": "LT-0001", "category": "Laptop", "description": "Dell Latitude 5440",
            "employee_id": user("employee").employee.id, "issued_on": "2026-10-01", "status": "Issued"}
    data.update(overrides)
    return client.post("/admin/assets/new", data=data, follow_redirects=True)


def test_ict_issues_an_asset_and_it_is_audited(client):
    login(client, "it")
    r = _issue(client)
    assert b"Asset LT-0001 saved" in r.data
    asset = Asset.query.filter_by(asset_tag="LT-0001").one()
    assert asset.employee == user("employee").employee and asset.status == "Issued"
    assert AuditLog.query.filter_by(action="asset.saved", entity_id=str(asset.id)).count() == 1
    assert b"LT-0001" in client.get("/admin/assets?q=employee").data


def test_asset_tag_must_be_unique(client):
    login(client, "it")
    _issue(client)
    r = _issue(client, description="Another laptop")
    assert b"already on the register" in r.data
    assert Asset.query.filter_by(asset_tag="LT-0001").count() == 1


def test_returning_an_asset_dates_it(client):
    login(client, "it")
    _issue(client)
    asset = Asset.query.filter_by(asset_tag="LT-0001").one()
    client.post(f"/admin/assets/{asset.id}", data={"asset_tag": "LT-0001", "employee_id": asset.employee_id,
                                                   "status": "Returned"})
    db.session.refresh(asset)
    assert asset.status == "Returned" and asset.returned_on is not None
    assert b"LT-0001" in client.get("/admin/assets?status=Returned").data
    assert b"LT-0001" not in client.get("/admin/assets?status=Issued").data


def test_asset_form_pages_render(client):
    login(client, "it")
    assert b"Issue Asset" in client.get("/admin/assets/new").data
    _issue(client)
    asset = Asset.query.filter_by(asset_tag="LT-0001").one()
    page = client.get(f"/admin/assets/{asset.id}").data
    assert b'value="LT-0001"' in page and b'value="2026-10-01"' in page


def test_allocation_form_attaches_and_only_ict_can_open_it(client):
    from io import BytesIO
    from app.models import StoredFile
    login(client, "it")
    r = _issue(client, allocation_form=(BytesIO(b"%PDF-1.4 signed"), "allocation.pdf"))
    assert b"Asset LT-0001 saved" in r.data
    asset = Asset.query.filter_by(asset_tag="LT-0001").one()
    stored = StoredFile.query.filter_by(entity_type="asset_allocation", entity_id=asset.id).one()
    assert b"allocation.pdf" in client.get(f"/admin/assets/{asset.id}").data
    assert b"Not attached" not in client.get("/admin/assets").data
    assert client.get(f"/files/{stored.id}").status_code == 200
    client.post("/logout")
    login(client, "hradmin")
    assert client.get(f"/files/{stored.id}").status_code == 403


def test_allocation_form_rejects_bad_file_type(client):
    from io import BytesIO
    login(client, "it")
    r = _issue(client, allocation_form=(BytesIO(b"MZ"), "virus.exe"))
    assert b"allowed file type" in r.data
    assert Asset.query.filter_by(asset_tag="LT-0001").count() == 0
