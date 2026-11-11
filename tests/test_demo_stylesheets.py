import re
from html.parser import HTMLParser
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "demo" / "static"


class Stylesheets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.in_head = True
        elif tag == "link" and "stylesheet" in dict(attrs).get("rel", "").split():
            self.links.append((self.in_head, dict(attrs)))

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


def test_demo_stylesheet_order_and_imports():
    page = Stylesheets()
    page.feed((STATIC / "index.html").read_text(encoding="utf-8"))
    hrefs = [
        "./design/tokens.css",
        "./design/base.css",
        "./design/controls.css",
        "./app.css",
    ]
    assert page.links == [(True, {"rel": "stylesheet", "href": href}) for href in hrefs]

    # The copied design entrypoint defines the order that the page must preserve.
    entrypoint = (STATIC / "design/index.css").read_text(encoding="utf-8")
    imports = re.findall(r"@import\s+['\"]([^'\"]+)['\"]\s*;", entrypoint)
    assert re.sub(r"@import\s+['\"][^'\"]+['\"]\s*;", "", entrypoint).strip() == ""
    assert [f"./design/{path.removeprefix('./')}" for path in imports] == hrefs[:-1]

    for href in hrefs:
        css = (STATIC / href).read_text(encoding="utf-8")
        assert not re.search(r"@import\b", css, re.IGNORECASE), href
