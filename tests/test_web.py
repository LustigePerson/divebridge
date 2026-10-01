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
