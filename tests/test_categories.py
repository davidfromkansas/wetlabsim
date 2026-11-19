"""The library's category tree (playground/category_tree.json) and each object's place in it
(playground/categories.json): every tagged object sits on a real path of the tree."""
from playground import catalog


def _paths():
    out = set()
    for a, l2 in catalog.CATEGORY_TREE.items():
        out.add((a,))
        for b, l3 in l2.items():
            out.add((a, b))
            out.update((a, b, c) for c in l3)
    return out


def test_every_tag_is_a_path_of_the_tree():
    paths = _paths()
    bad = {i: p for i, p in catalog.CATEGORIES.items() if tuple(p) not in paths}
    assert not bad, list(bad.items())[:10]


def test_tags_name_library_items():
    ids = {row[0] for row in catalog.ITEMS}
    assert set(catalog.CATEGORIES) <= ids


def test_catalog_items_carry_their_path():
    for it in catalog.available()[:200]:
        assert it["cat"] and it["cat"] == catalog.category(it["id"], it["tab"])
