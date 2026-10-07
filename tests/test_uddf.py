import xml.etree.ElementTree as ET

from divebridge.exporters.uddf import UDDF_NS, dives_to_uddf, uddf_filename

NS = {"u": UDDF_NS}


def test_uddf_structure(sample_dives):
    xml = dives_to_uddf(sample_dives)
    root = ET.fromstring(xml)
    assert root.tag == f"{{{UDDF_NS}}}uddf"
    assert root.get("version") == "3.2.3"
    dives = root.findall("u:profiledata/u:repetitiongroup/u:dive", NS)
    assert len(dives) == 1
    dive = dives[0]
    assert dive.find("u:informationbeforedive/u:datetime", NS).text == "2025-10-15T02:56:07"
    assert dive.find("u:informationbeforedive/u:divenumber", NS).text == "1"
    wps = dive.findall("u:samples/u:waypoint", NS)
    assert len(wps) == 634
    assert wps[0].find("u:depth", NS).text == "2.80"
    assert wps[0].find("u:temperature", NS).text == "297.05"  # 23.9 °C in Kelvin
    assert wps[0].find("u:switchmix", NS) is not None
    after = dive.find("u:informationafterdive", NS)
    assert after.find("u:greatestdepth", NS).text == "38.09"
    assert after.find("u:diveduration", NS).text == "1319"
    assert root.find("u:divesite/u:site/u:name", NS).text == "Monterey"
    assert root.find("u:gasdefinitions/u:mix/u:o2", NS).text == "0.210"
    assert root.find("u:diver/u:owner/u:equipment/u:divecomputer/u:serialnumber", NS).text == "000002"
    assert root.find("u:diver/u:owner/u:equipment/u:divecomputer/u:name", NS).text == "XS Scuba Skiff"


def test_uddf_filename(sample_dives):
    assert uddf_filename(sample_dives[0]) == "2025-10-15_0256_000002.uddf"
