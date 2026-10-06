"""Lua files in and out, for the Gargoyle app.

Out: `to_lua()` writes Python data as a Lua table for the Gargoyle_Sync data addon. This
is the one place website text (raid titles and notes typed by other players) turns into a
file the game runs, so it's strict: only plain data (dicts, lists, strings, numbers,
booleans), and every string is quoted with backslashes, quotes and control characters
escaped. No text, whatever it contains, can end a string early and become code.

In: `read_saved()` reads a SavedVariables file the game wrote (GargoyleDB). It's parsed as
data, never run: only tables, strings, numbers, booleans and nil are understood, with
limits on size and nesting, and anything else is an error.
"""
import math
import re

MAX_BYTES = 20 * 1024 * 1024
MAX_DEPTH = 30
LUA_KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in", "local", "nil",
    "not", "or", "repeat", "return", "then", "true", "until", "while",
}
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LuaError(ValueError):
    pass


# ---- Writing ----

def lua_string(text):
    """A Lua string literal: backslash, quote and every control character escaped
    (as \\ddd), so it always ends exactly where it should."""
    text = text.encode("utf-8", "replace").decode("utf-8")  # (drops broken characters)
    out = ['"']
    for ch in text:
        code = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif code < 32 or code == 127:
            out.append(f"\\{code:03d}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _key(key):
    if isinstance(key, bool):
        raise LuaError("a table key can't be true/false")
    if isinstance(key, int):
        return f"[{key}]"
    if isinstance(key, str):
        return key if NAME.match(key) and key not in LUA_KEYWORDS else f"[{lua_string(key)}]"
    raise LuaError(f"a table key can't be {type(key).__name__}")


def to_lua(value, depth=0):
    """Plain data as Lua source. None inside a dict is left out; lists can't hold None."""
    if depth > MAX_DEPTH:
        raise LuaError("too deeply nested")
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else "0"
    if isinstance(value, str):
        return lua_string(value)
    pad = "  " * (depth + 1)
    if isinstance(value, (list, tuple)):
        if not value:
            return "{}"
        if any(v is None for v in value):
            raise LuaError("a list can't hold nil")
        return "{\n" + "".join(f"{pad}{to_lua(v, depth + 1)},\n" for v in value) + "  " * depth + "}"
    if isinstance(value, dict):
        items = [(k, v) for k, v in value.items() if v is not None]
        if not items:
            return "{}"
        return "{\n" + "".join(f"{pad}{_key(k)} = {to_lua(v, depth + 1)},\n" for k, v in items) + "  " * depth + "}"
    raise LuaError(f"can't write {type(value).__name__} as Lua")


# ---- Reading ----

TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<comment>--[^\n]*)
  | (?P<string>"(?:[^"\\\n]|\\.|\\\n)*")
  | (?P<number>-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?))
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<punct>[{}\[\]=,;])
""", re.X | re.S)

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v", "\\": "\\", '"': '"', "'": "'", "\n": "\n"}


def _unquote(literal):
    body, out, i = literal[1:-1], [], 0
    raw = bytearray()

    def flush():
        if raw:
            out.append(raw.decode("utf-8", "replace"))
            raw.clear()

    while i < len(body):
        ch = body[i]
        if ch != "\\":
            flush()
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt.isdigit():
            digits = re.match(r"\d{1,3}", body[i + 1:]).group(0)
            code = int(digits)
            if code > 255:
                raise LuaError("bad escape in a string")
            raw.append(code)  # (bytes: a UTF-8 character may be written as several)
            i += 1 + len(digits)
            continue
        if nxt not in ESCAPES:
            raise LuaError("bad escape in a string")
        flush()
        out.append(ESCAPES[nxt])
        i += 2
    flush()
    return "".join(out)


def _tokens(text):
    pos = 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise LuaError(f"unexpected text at character {pos}")
        pos = m.end()
        kind = m.lastgroup
        if kind not in ("space", "comment"):
            yield kind, m.group(kind)


class _Parser:
    def __init__(self, text):
        self.tokens = list(_tokens(text))
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def take(self, value=None):
        kind, tok = self.peek()
        if kind is None or (value is not None and tok != value):
            raise LuaError(f"expected {value or 'more'}, found {tok!r}")
        self.i += 1
        return kind, tok

    def value(self, depth):
        kind, tok = self.peek()
        if kind == "string":
            self.i += 1
            return _unquote(tok)
        if kind == "number":
            self.i += 1
            number = float.fromhex(tok) if "x" in tok.lower() else float(tok)
            return int(number) if number.is_integer() and abs(number) < 2**53 else number
        if kind == "name" and tok in ("true", "false", "nil"):
            self.i += 1
            return {"true": True, "false": False, "nil": None}[tok]
        if tok == "{":
            return self.table(depth + 1)
        raise LuaError(f"unexpected {tok!r}")

    def table(self, depth):
        if depth > MAX_DEPTH:
            raise LuaError("too deeply nested")
        self.take("{")
        result, n = {}, 0
        while self.peek()[1] != "}":
            kind, tok = self.peek()
            if tok == "[":
                self.take("[")
                key = self.value(depth)
                self.take("]")
                self.take("=")
                result[key] = self.value(depth)
            elif kind == "name" and self.tokens[self.i + 1:self.i + 2] == [("punct", "=")]:
                self.i += 2
                result[tok] = self.value(depth)
            else:
                n += 1
                result[n] = self.value(depth)
            if self.peek()[1] in (",", ";"):
                self.i += 1
            elif self.peek()[1] != "}":
                raise LuaError(f"expected , or }} in a table, found {self.peek()[1]!r}")
        self.take("}")
        result = {k: v for k, v in result.items() if v is not None}
        # A table numbered 1..n is a list.
        if result and all(isinstance(k, int) and not isinstance(k, bool) for k in result) and \
                sorted(result) == list(range(1, len(result) + 1)):
            return [result[k] for k in range(1, len(result) + 1)]
        return result


def read_saved(text):
    """{variable name: value} from a SavedVariables file's text."""
    if len(text) > MAX_BYTES:
        raise LuaError("file too large")
    parser, found = _Parser(text), {}
    while parser.peek()[0] is not None:
        kind, name = parser.take()
        if kind != "name" or name in LUA_KEYWORDS:
            raise LuaError(f"expected a variable name, found {name!r}")
        parser.take("=")
        found[name] = parser.value(0)
    return found
