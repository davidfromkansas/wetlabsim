"""The drag preview: one library object on its own (scene3d.item_model), drawn by the page while
the object is dragged in. Uses a small stand-in object, so it needs no library files."""
import json

import numpy as np
import pytest
from PIL import Image

from playground import catalog, scene3d as S3, world as W

ITEM = "co2_incubator"         # any library id: its files here are a stand-in


@pytest.fixture
def assets(tmp_path, monkeypatch):
    d = tmp_path / ITEM
    d.mkdir()
    box = [(x, y, z) for x in (-.15, .15) for y in (-.1, .1) for z in (0, .4)]
    faces = [(1, 2, 4), (1, 4, 3), (5, 7, 8), (5, 8, 6), (1, 5, 6), (1, 6, 2),
             (3, 4, 8), (3, 8, 7), (1, 3, 7), (1, 7, 5), (2, 6, 8), (2, 8, 4)]
    for name in ("vis.obj", "col.obj"):
        (d / name).write_text("".join(f"v {x} {y} {z}\n" for x, y, z in box)
                              + "".join(f"f {a} {b} {c}\n" for a, b, c in faces))
    Image.new("RGB", (8, 8), (200, 40, 40)).save(d / "tex.png")
    (d / "asset.json").write_text(json.dumps({
        "size": [0.3, 0.2, 0.4], "mass": 2.0,
        "visuals": [{"mesh": "vis.obj", "texture": "tex.png", "rgba": [1, 1, 1, 1]}],
        "collision_parts": [{"mesh": "col.obj", "volume": 0.024}], "inertial": None}))
    monkeypatch.setattr(catalog, "ASSETS", tmp_path)
    S3._ITEM_MODELS.clear()
    yield tmp_path
    S3._ITEM_MODELS.clear()


def test_item_scene_in_its_own_frame(assets):
    m, sc = S3.item_model(ITEM)
    assert len(sc["geoms"]) == 1 and len(sc["hulls"]) == 1
    g = sc["geoms"][0]
    # its bottom centre at the origin: the box's middle 20 cm up
    assert np.allclose(g["pos"], [0, 0, 0.2], atol=1e-4)
    assert g["tex"] >= 0 and str(g["tex"]) in sc["texhash"]
    assert S3.item_model(ITEM)[0] is m          # built once


def test_preview_meshes_are_the_worlds(assets):
    """The preview's meshes and textures have the same content hashes as once the object is in a
    world, so what the page fetched for the preview is reused after the drop."""
    _, sc = S3.item_model(ITEM)
    world = W.build([W.Placed("x1", ITEM, (0.4, 0.2, 0.75), 0.7)], [])
    wsc = S3.scene(world, 0)
    assert set(sc["meshhash"].values()) <= set(wsc["meshhash"].values()) | set(S3._info(world)["mesh"])
    assert set(sc["texhash"].values()) <= set(wsc["texhash"].values())
    assert all(b is not None for b in S3.mesh_by_hash(S3.item_model(ITEM)[0], list(sc["meshhash"].values())))


def test_unknown_item(assets):
    with pytest.raises(KeyError):
        S3.item_model("no_such_thing")
