#!/usr/bin/env bash
# Build the Google Scanned Objects and RoboCasa sets into the object library, start to finish
# (see playground/tools/build_mjcf_sets.py). Each step skips what is already done, so it can be
# run again after a stop. Needs ~60 GB free while it runs, a Modal login for the last step, and
# the repo's own venv active (.venv). Run from the repo root:
#
#     bash scripts/build_mjcf_sets.sh [workers]
set -euo pipefail
W=${1:-4}
B=build
mkdir -p $B
PY=$(command -v python)

# 0. The rest of the library, so the uploaded index lists every object
python -m playground.tools.library pull | tail -1

# 1. Google Scanned Objects as MuJoCo models (~1.2 GB)
[ -d $B/gso/models ] || git clone --depth 1 https://github.com/kevinzakka/mujoco_scanned_objects $B/gso

# 2. RoboCasa's own code, in its own venv (it pins MuJoCo 3.3.1 and numpy 2.2.5)
[ -d $B/robosuite ] || git clone --depth 1 https://github.com/ARISE-Initiative/robosuite $B/robosuite
[ -d $B/robocasa ] || git clone --depth 1 https://github.com/robocasa/robocasa $B/robocasa
if [ ! -x $B/rcvenv/bin/python ]; then
  python3 -m venv $B/rcvenv
  $B/rcvenv/bin/pip install -q mujoco==3.3.1 numpy==2.2.5 scipy==1.15.3 numba lxml termcolor tqdm pyyaml \
      pillow opencv-python-headless h5py imageio gymnasium pygame
  $B/rcvenv/bin/pip install -q --no-deps -e $B/robosuite -e $B/robocasa
fi

# 3. RoboCasa's objects and fixtures (~9.3 GB of zips, from RoboCasa's own links)
RA=$B/robocasa/robocasa/models/assets
LINKS=$RA/box_links/box_links_assets.json
get() {  # key folder
  [ -f "$2/.done" ] && return
  local id; id=$($PY -c "import json,sys; print(json.load(open('$LINKS'))['$1'].rstrip('/').split('/')[-1])")
  mkdir -p "$2"
  curl -sSL --retry 5 -o $B/$1.zip "https://utexas.box.com/shared/static/$id.zip"
  unzip -q -o $B/$1.zip -d "$(dirname "$2")"
  rm $B/$1.zip
  touch "$2/.done"
}
get aigen_objs $RA/objects/aigen_objs
get objaverse $RA/objects/objaverse
get objects_lightwheel $RA/objects/lightwheel
get fixtures_lightwheel $RA/fixtures

# 4. Export them as RoboCasa loads them
(cd /tmp && "$OLDPWD/$B/rcvenv/bin/python" "$OLDPWD/playground/tools/export_robocasa.py" "$OLDPWD/$B/robocasa_export") 2>&1 \
  | grep -v WARNING | tail -5

# 5. Build, drop-test, finish
python -m playground.tools.build_mjcf_sets pick --gso $B/gso --robocasa $B/robocasa_export
python -m playground.tools.build_mjcf_sets build --gso $B/gso --robocasa $B/robocasa_export --workers "$W" | tail -3
IDS=$(python -c "import json; print(' '.join(r['id'] for r in json.load(open('playground/mjcf_library.json'))))")
python -m playground.tools.check_usdcraft --out $B/mjcf_check.json --jobs "$W" $IDS | tail -3
python -m playground.tools.build_mjcf_sets finish
python -c "from playground.tools.build_assets import write_credits; write_credits()"

# 6. Upload to the Modal Volume the site reads the library from
python -m playground.tools.library push $IDS
