from divebridge.ssi.check import TEST_DIVE_NOTE, run_check


class FakeClient:
    """Stores what it gets; `broken` makes save_divelog answer the 2026-10-07 stub."""

    def __init__(self, broken=False):
        self.broken = broken
        self.dives = []
        self.next_id = 100

    def forget_token(self): pass
    def authenticate(self): return "tok"
    def get_user_data(self): return {"user_forename": "Test", "user_lastname": "Diver"}
    def get_divelog_vars(self): return {"logbook_vars": {"watertype": {"4": "fresh", "5": "salt"}}}
    def get_divelog(self): return {"logbook_details": [d for d in self.dives if not d.get("odin_user_log_deleted")]}

    def save_divelog(self, payload):
        if self.broken:
            return {"success": {"ok": "added to Log", "error": "", "temp_id": "", "odin_user_log_id": 999}}
        if payload.get("odin_user_log_deleted"):
            for d in self.dives:
                if d["odin_user_log_id"] == payload["odin_user_log_id"]:
                    d["odin_user_log_deleted"] = 1
            return {"success": {"ok": "deleted"}}
        rec = dict(payload, odin_user_log_id=self.next_id); self.next_id += 1
        self.dives.append(rec)
        return dict(rec)


def test_read_check_ok(tmp_path, monkeypatch):
    import divebridge.ssi.check as chk
    monkeypatch.setattr(chk.SiteIndex, "ensure", lambda self, force=False: None)
    monkeypatch.setattr(chk.SiteIndex, "__len__", lambda self: 3)
    res = run_check(FakeClient(), "read", tmp_path)
    assert res.ok and [s.name for s in res.steps] == ["authenticate", "get_user_data", "get_divelog", "get_divelog_vars", "sites"]
    assert "ok" in res.summary()


def test_write_check_round_trip(tmp_path, monkeypatch):
    import divebridge.ssi.check as chk
    monkeypatch.setattr(chk.SiteIndex, "ensure", lambda self, force=False: None)
    monkeypatch.setattr(chk.SiteIndex, "__len__", lambda self: 3)
    c = FakeClient()
    res = run_check(c, "write", tmp_path)
    assert res.ok, res.summary()
    names = [s.name for s in res.steps]
    assert names[-4:] == ["save_divelog", "read back", "delete", "read back after delete"]
    assert c.get_divelog()["logbook_details"] == []            # test dive removed again
    assert c.dives[0]["odin_user_log_comment"] == TEST_DIVE_NOTE
    assert c.dives[0]["odin_user_log_date"] == "2000-01-01"


def test_write_check_detects_stub(tmp_path, monkeypatch):
    import divebridge.ssi.check as chk
    monkeypatch.setattr(chk.SiteIndex, "ensure", lambda self, force=False: None)
    monkeypatch.setattr(chk.SiteIndex, "__len__", lambda self: 3)
    res = run_check(FakeClient(broken=True), "write", tmp_path)
    assert not res.ok
    failed = [s for s in res.steps if not s.ok]
    assert failed and failed[0].name == "read back" and "not in logbook" in failed[0].detail
    assert "FAILED" in res.summary()
    d = res.to_dict(); assert d["ok"] is False and d["level"] == "write"
