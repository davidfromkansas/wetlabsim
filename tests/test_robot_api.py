"""The robot API's gate: which requests an agent's run token can make."""
from wetlabsim import robot_api as RA


def test_allowed_paths():
    for m, p in [("GET", "/state"), ("GET", "/info"), ("GET", "/camera/overhead.png"),
                 ("GET", "/camera/wrist.rgbd.npz"), ("POST", "/move_l"), ("POST", "/gripper"),
                 ("POST", "/stop"), ("POST", "/unlock_protective_stop")]:
        assert RA.allowed(m, p), (m, p)


def test_refused_paths():
    # the audience camera, the app, the evaluator, run history and files are not the robot
    for m, p in [("GET", "/camera/side.jpg"), ("GET", "/pg/scene"), ("POST", "/pg/play"),
                 ("GET", "/eval/ground_truth"), ("POST", "/eval/reset"), ("GET", "/run/files"),
                 ("GET", "/trace"), ("GET", "/runs"), ("GET", "/history/state"), ("POST", "/state"),
                 ("GET", "/move_l"), ("GET", "/st/st1/state")]:
        assert not RA.allowed(m, p), (m, p)


def test_token_lifecycle():
    toks = RA.RunTokens()
    t = toks.issue("/st/st2/", run="test")
    assert toks.lookup(t)["prefix"] == "/st/st2"
    assert toks.lookup("wrong") is None and toks.lookup("") is None
    toks.revoke(t)
    assert toks.lookup(t) is None


def test_token_header():
    assert RA.token_from({"Authorization": "Bearer abc"}) == "abc"
    assert RA.token_from({"X-Robot-Token": "xyz"}) == "xyz"
    assert RA.token_from({}) == ""
