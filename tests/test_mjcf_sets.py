"""Google Scanned Objects and RoboCasa items (tools/build_mjcf_sets.py): each is listed with its
source and citation, and the built ones load, keep their source's mass and settle when dropped."""
import json

import pytest

from playground import catalog

ROWS = [r for r in catalog.MJCF_SETS if not r.get("skip")]
BUILT = [r["id"] for r in ROWS if (catalog.ASSETS / r["id"] / "asset.json").exists()]


def test_rows_have_source_and_citation():
    for r in ROWS:
        it = catalog.item(r["id"])
        assert catalog.source(it["hf"]) in ("Scanned Objects", "RoboCasa")
        assert catalog.citation(it["hf"])
        assert r["tab"] in catalog.TABS


def test_fixtures_stay_put():
    assert all(r["fixed"] for r in ROWS if r["id"].startswith("rc_fx_"))


@pytest.mark.skipif(not BUILT, reason="no Scanned Objects / RoboCasa items built here")
@pytest.mark.parametrize("id_", BUILT[:3] + [i for i in BUILT if i.startswith("rc_")][:3])
def test_built_item_loads_and_settles(id_):
    from playground.tools.check_usdcraft import check
    meta = json.loads((catalog.ASSETS / id_ / "asset.json").read_text())
    assert meta["mjcf"] == "model.xml" and meta["mass"] > 0 and "CC BY 4.0" in meta["license"]
    r = check(id_)
    assert r["ok"], r["why"]
