from divebridge.ssi.payload import build_payload
from divebridge.ssi.verify import compare, summarize


def test_compare_roundtrip(sample_dives):
    p = build_payload(sample_dives[0], log_nr=9, site_id=5)
    stored = dict(p)
    stored["odin_user_log_depth_m"] = "38.1"          # SSI returns strings / rounded values
    stored["odin_user_log_weight_kg"] = 0               # unset comes back as 0
    stored["odin_user_log_si_before"] = 7               # pretend SSI converted seconds to minutes
    diffs = compare(p, stored)
    bad = {d.label for d in diffs if not d.ok}
    assert bad == {"surface interval"}
    assert "surface interval" in summarize(diffs)
