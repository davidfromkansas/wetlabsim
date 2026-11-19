"""The phone layout (playground/static/mobile.js) is part of the page, versioned like the others."""
from playground import server


def test_page_loads_mobile_layout():
    page = server._page().decode()
    assert '/pg/static/mobile.js?v=' in page
    assert 'mobile.js?v=HASH' not in page
    assert (server.HERE / 'static' / 'mobile.js').exists()
