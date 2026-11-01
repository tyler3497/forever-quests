#!/usr/bin/env python3
"""Regenerate data/QuestDB.lua from data/quests.json + data/zones.json.
Usage: python3 tools/build_lua.py [version]
"""
import json
import sys


def lua_escape(s):
    out = []
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 32:
            out.append("\\%03d" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def to_lua(v, depth):
    pad = "  " * (depth + 1)
    close = "  " * depth
    if v is None:
        return "nil"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return lua_escape(v)
    if isinstance(v, list):
        if not v:
            return "{}"
        parts = [pad + to_lua(x, depth + 1) + "," for x in v]
        return "{\n" + "\n".join(parts) + "\n" + close + "}"
    if isinstance(v, dict):
        if not v:
            return "{}"
        parts = []
        for k in sorted(v, key=str):
            ks = "[%d]" % k if isinstance(k, int) else "[" + lua_escape(str(k)) + "]"
            parts.append(pad + ks + " = " + to_lua(v[k], depth + 1) + ",")
        return "{\n" + "\n".join(parts) + "\n" + close + "}"
    raise TypeError(type(v))


def main():
    repo = __file__.rsplit("/tools/", 1)[0]
    version = sys.argv[1] if len(sys.argv) > 1 else "1.2.0"
    quests = json.load(open(repo + "/data/quests.json"))
    zones = json.load(open(repo + "/data/zones.json"))
    lua_data = {"version": version,
                "quests": {int(k): v for k, v in quests.items()},
                "zones": zones}
    with open(repo + "/data/QuestDB.lua", "w") as f:
        f.write("-- Generated from data/quests.json by tools/build_lua.py. "
                "Do not edit by hand.\n")
        f.write("ForeverQuestsDB = " + to_lua(lua_data, 0) + "\n")


if __name__ == "__main__":
    main()
