import json

from divebridge.ssi.sites import SiteIndex


def test_search_ranking_and_prefer(tmp_path):
    doc = {"divesites": [
        {"odin_dive_sites_id": 1, "odin_dive_sites_name": "Blue Hole", "odin_dive_sites_meta_country": "Belize", "bow": "salt"},
        {"odin_dive_sites_id": 2, "odin_dive_sites_name": "Blue Hole", "odin_dive_sites_meta_country": "Egypt", "bow": "salt"},
        {"odin_dive_sites_id": 3, "odin_dive_sites_name": "Blue Hole Lake", "odin_dive_sites_meta_country": "Germany", "bow": "fresh"},
        {"odin_dive_sites_id": 4, "odin_dive_sites_name": "Deleted", "odin_dive_sites_deleted": 1},
    ]}
    (tmp_path / "ssi-sites.json").write_text(json.dumps(doc))
    idx = SiteIndex(tmp_path)
    assert [m.id for m in idx.search("blue hole")] == [1, 2, 3]      # exact matches first, then prefix
    assert [m.id for m in idx.search("blue hole", prefer={2})][0] == 2  # visited site wins
    assert idx.search("x") == []
    assert idx.get(3).bow == "fresh" and idx.get(4) is None
