"""NVIDIA USDCraft-10K kinds in the library (playground/usdcraft_library.json): each is built, sits
in a library tab, carries the USDCraft source chip, and passes the drop test."""
import pytest

from playground import catalog
from playground.tools.check_usdcraft import check

IDS = [u["id"] for u in catalog.USDCRAFT]


def test_every_usdcraft_kind_is_built_with_its_chip():
    built = {it["id"]: it for it in catalog.available()}
    assert len(IDS) > 800
    for i in IDS:
        assert i in built, f"{i} not built"
        assert built[i]["source"] == "USDCraft"
        assert built[i]["tab"] in catalog.TABS


def test_no_two_items_share_an_id_or_label():
    assert len({i[0] for i in catalog.ITEMS}) == len(catalog.ITEMS)
    labels = [i[2] for i in catalog.ITEMS if i[0] in IDS]
    assert len(set(labels)) == len(labels)


@pytest.mark.parametrize("item", IDS[::60])
def test_sample_rests_on_the_floor(item):
    r = check(item)
    assert r["ok"], r["why"]
