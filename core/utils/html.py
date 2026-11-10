import re

import nh3

# What the admin rich text editor produces: the frontend renders this HTML as is.
RICH_TEXT_TAGS = {"p", "br", "strong", "em", "u", "s", "ul", "ol", "li", "a"}

EMPTY_RICH_TEXT_RE = re.compile(r"^(\s|<p>|</p>|<br\s*/?>)*$")


def sanitize_rich_text(html: str) -> str:
    cleaned = nh3.clean(
        html,
        tags=RICH_TEXT_TAGS,
        attributes={"a": {"href"}},
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
        set_tag_attribute_values={"a": {"target": "_blank"}},
    ).strip()

    # An emptied editor still sends "<p></p>".
    return "" if EMPTY_RICH_TEXT_RE.match(cleaned) else cleaned
