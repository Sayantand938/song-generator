import re

try:
    from titlecase import titlecase
except ImportError:
    def titlecase(t):
        return " ".join(w.capitalize() for w in t.split())


def to_title_case(text: str) -> str:
    clean = re.sub(r"[\-_]+", " ", text).strip()
    clean = re.sub(r"\s+", " ", clean)
    return titlecase(clean) if clean else text