from paperful.ui.md import md_to_html


def test_headings_and_bold():
    html = str(md_to_html("## Hello\n\nThis is **bold** and *italic*."))
    assert "<h2>Hello</h2>" in html
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html


def test_script_tags_stay_escaped():
    html = str(md_to_html("<script>alert(1)</script>"))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_javascript_url_is_not_an_href():
    html = str(md_to_html("[x](javascript:alert(1))"))
    assert "href=" not in html
    assert "javascript:" not in html
    assert "x" in html


def test_https_link_is_href():
    html = str(md_to_html("[ex](https://example.com/a)"))
    assert 'href="https://example.com/a"' in html
    assert ">ex</a>" in html


def test_list_items():
    html = str(md_to_html("- one\n- two"))
    assert html == "<ul><li>one</li><li>two</li></ul>"
