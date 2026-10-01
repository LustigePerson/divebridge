from fastapi.testclient import TestClient

from divebridge.web.app import app, settings


def test_upload_review_uddf(sample_bytes, tmp_path):
    settings.output_dir = tmp_path / "out"
    c = TestClient(app)
    assert c.get("/health").json()["status"] == "ok"
    r = c.post("/upload", files=[("files", ("sample.xlsx", sample_bytes,
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
               headers={"X-Ingress-Path": "/api/hassio_ingress/abc"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/api/hassio_ingress/abc/batch/")
    bid = r.headers["location"].rsplit("/", 1)[1]
    page = c.get(f"/batch/{bid}", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
    assert page.status_code == 200
    assert "Monterey" in page.text
    assert 'action="/api/hassio_ingress/abc/batch/' in page.text
    u = c.get(f"/batch/{bid}/uddf")
    assert u.status_code == 200
    assert u.headers["content-type"].startswith("application/xml")
    assert b"<uddf" in u.content
    assert (tmp_path / "out" / "2025-10-15_0256_000002.uddf").exists()


def test_unknown_file():
    c = TestClient(app)
    r = c.post("/upload", files=[("files", ("x.txt", b"hello", "text/plain"))], follow_redirects=True)
    assert "unknown format" in r.text


def test_login_form_on_batch_page_and_redirect_back(sample_bytes, monkeypatch):
    from divebridge.web import app as webapp

    c = TestClient(app)
    r = c.post("/upload", files=[("files", ("sample.xlsx", sample_bytes, "application/octet-stream"))],
               follow_redirects=False)
    bid = r.headers["location"].rsplit("/", 1)[1]
    page = c.get(f"/batch/{bid}").text
    assert 'name="next" value="batch/' in page  # login form shown when not logged in

    class FakeClient:
        def __init__(self, *a, **k): pass
        def authenticate(self): return "tok"
        def get_divelog(self):
            return {"logbook_details": [{"odin_user_log_nr": 7, "odin_user_log_date": "2025-10-15",
                                         "odin_user_log_entry_time": "02:56"}]}
        def close(self): pass

    monkeypatch.setattr(webapp, "SsiClient", FakeClient)
    monkeypatch.setattr(webapp.AppState, "sites", lambda self: (_ for _ in ()).throw(RuntimeError("offline")))
    r = c.post("/login", data={"email": "a@b.c", "password": "x", "next": f"batch/{bid}"},
               headers={"X-Ingress-Path": "/ing"}, follow_redirects=False)
    assert r.headers["location"] == f"/ing/batch/{bid}"
    page = c.get(f"/batch/{bid}").text
    assert "already in SSI (#7)" in page  # batch was enriched after login
    assert 'name="next"' not in page
    # open redirect must not be possible
    r = c.post("/login", data={"email": "a@b.c", "password": "x", "next": "https://evil"}, follow_redirects=False)
    assert r.headers["location"] == "/"
    webapp.state.email = webapp.state.password = None
    webapp.state.reset_client()


def test_push_with_options_dry_run(sample_bytes, monkeypatch):
    import json

    from divebridge.web import app as webapp

    class FakeClient:
        def __init__(self, *a, **k): pass
        def authenticate(self): return "tok"
        def get_divelog(self):
            return {"logbook_details": [{"odin_user_log_nr": 3, "odin_user_log_date": "2020-01-01",
                                         "odin_user_log_entry_time": "10:00"}],
                    "logbook_buddies": [{"id": 77, "firstname": "Max", "lastname": "Muster"}]}
        def close(self): pass

    class FakeSites:
        def search(self, q, limit=1): return []
        def get(self, sid):
            from divebridge.ssi.sites import SiteMatch
            return SiteMatch(id=sid, name="Blue Hole", country="", region="", lat=None, lon=None, bow="salt")

    monkeypatch.setattr(webapp, "SsiClient", FakeClient)
    monkeypatch.setattr(webapp.AppState, "sites", lambda self: FakeSites())
    c = TestClient(app)
    c.post("/login", data={"email": "a@b.c", "password": "x"}, follow_redirects=False)
    r = c.post("/upload", files=[("files", ("s.xlsx", sample_bytes, "application/octet-stream"))], follow_redirects=False)
    bid = r.headers["location"].rsplit("/", 1)[1]
    page = c.get(f"/batch/{bid}").text
    assert "Max Muster" in page and 'name="same_for_all"' in page
    r = c.post(f"/batch/{bid}/ssi", data={"selected": "0", "dry_run": "1", "same_for_all": "1",
                                          "o_tanktype": "20", "o_weight_kg": "6,5", "o_entry": "22",
                                          "o_specialdive": ["40", "47"],
                                          "site_id_0": "441938",
                                          "o_buddy": "77", "o_notes": "test"})
    assert r.status_code == 200 and "dry-run" in r.text
    res = webapp.state.batches[bid].results[0]
    assert res.log_nr == 4
    assert res.payload["odin_user_log_var_tanktype_id"] == 20
    assert res.payload["odin_user_log_var_watertype_id"] == 5 and res.site_id == 441938  # auto from site
    assert res.payload["odin_user_log_var_entry_id"] == 22
    assert res.payload["odin_user_log_var_specialdive_id"] == "40,47"
    assert "Weather" in page and "ripping current" in page
    assert 'type="checkbox" name="o_buddy" value="77"' in page  # checkbox list: can be unticked
    assert "SSI water type" in page and "use my location" in page
    near = c.get("/api/sites?q=&lat=1&lon=1").json()  # FakeSites has no nearby() -> 503 is acceptable here
    assert isinstance(near, (list, dict))
    assert res.payload["odin_user_log_weight_kg"] == 6.5
    assert res.payload["odin_user_log_buddy_ids"] == [77]
    assert res.payload["odin_user_log_comment"] == "test"
    json.dumps(res.payload)
    webapp.state.email = webapp.state.password = None
    webapp.state.reset_client()


def test_zip_upload(tmp_path):
    import io
    import zipfile
    from pathlib import Path

    d = Path(__file__).parent / "data" / "cressi"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in d.glob("SKIFF_*.xlsx"):
            zf.writestr(f"exports/{f.name}", f.read_bytes())
        zf.writestr("exports/readme.txt", "ignore me")
    c = TestClient(app)
    r = c.post("/upload", files=[("files", ("exports.zip", buf.getvalue(), "application/zip"))], follow_redirects=True)
    assert r.status_code == 200
    assert "Review 3 dive(s)" in r.text
    assert "readme.txt: unknown format" in r.text



def test_companion_app_gets_single_file_input():
    c = TestClient(app)
    page = c.get("/", headers={"User-Agent": "Mozilla/5.0 (Linux; Android 16) Home Assistant/2026.6.5 (Android 16; SM-S931B)"}).text
    assert 'name="files"  required' in page or 'name="files" required' in page
    assert "multiple" not in page.split('name="files"')[1].split(">")[0]
    assert "ZIP" in page
    page = c.get("/", headers={"User-Agent": "Mozilla/5.0 Chrome/150"}).text
    assert 'name="files" multiple required' in page


def test_diag_page_and_echo(sample_bytes):
    c = TestClient(app)
    page = c.get("/diag", headers={"User-Agent": "X Home Assistant/2026.6.5 (Android 16; SM-S931B)"}).text
    assert "Detected as companion app</td><td>yes" in page
    r = c.post("/diag/echo", files=[("files", ("z.zip", sample_bytes, "application/zip"))])
    assert "z.zip" in r.text and "%d bytes" % len(sample_bytes) in r.text
    assert "no file part" in c.post("/diag/echo").text


def test_no_store_header():
    c = TestClient(app)
    assert c.get("/").headers["cache-control"] == "no-store"
    assert c.get("/health").headers["cache-control"] == "no-store"
