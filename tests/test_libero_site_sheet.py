"""The site sheet of a LIBERO room station names the table the robot works on: at about the
robot base's height and in front of it (the study and living rooms' tables are meshes, so the
biggest box there was a wall or shelf part)."""
import re

import pytest

from playground.sim import PlaygroundSim

ROOMS = ["STUDY_SCENE1_pick_up_the_book_and_place_it_in_the_back_compartment_of_the_caddy",
         "LIVING_ROOM_SCENE2_put_both_the_alphabet_soup_and_the_tomato_sauce_in_the_basket",
         "KITCHEN_SCENE3_turn_on_the_stove_and_put_the_moka_pot_on_it"]


@pytest.mark.parametrize("room", ROOMS)
def test_table_in_front_of_the_robot(room):
    s = PlaygroundSim()
    uid = s.add_station("franka", (6.0, 0.0), 0.7, kind="libero", task=room, free=True)
    sheet = s.libero_sheet(uid)
    m = re.search(r"plane z = (\S+) m\. It extends from x = (\S+) m to\s+x = (\S+) m and from y = (\S+) m to y = (\S+) m",
                  sheet)
    assert m, sheet
    z, x0, x1, y0, y1 = map(float, m.groups())
    assert -0.15 < z < 0.15                   # the base stands at about the table's height
    assert x0 < 0.5 < x1 and y0 < 0 < y1      # the table is in front of the robot
    assert x1 - x0 > 0.4 and y1 - y0 > 0.6    # a table, not a strip of one
