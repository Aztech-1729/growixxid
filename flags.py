"""Country flag emoji helpers — uses pycountry for name→code lookup."""
import pycountry

_FLAG_CACHE = {}


def flag_from_code(code: str) -> str:
    if len(code) != 2 or not code.isalpha():
        return ""
    code = code.upper()
    return chr(ord(code[0]) + 0x1F1E6 - ord("A")) + chr(
        ord(code[1]) + 0x1F1E6 - ord("A")
    )


def flag_from_name(name: str) -> str:
    if not name:
        return ""
    if name in _FLAG_CACHE:
        return _FLAG_CACHE[name]
    try:
        c = pycountry.countries.lookup(name)
        f = flag_from_code(c.alpha_2)
        _FLAG_CACHE[name] = f
        return f
    except Exception:
        _FLAG_CACHE[name] = ""
        return ""
