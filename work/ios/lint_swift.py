import pathlib
import re

PAT_LINE_COMMENT = re.compile(r"//[^\n]*")
PAT_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
PAT_STRING = re.compile(r'"(?:\\.|[^"\\])*"')

total = 0
for p in sorted(pathlib.Path(".").rglob("*.swift")):
    s = p.read_text(encoding="utf-8")
    t = PAT_BLOCK_COMMENT.sub("", PAT_LINE_COMMENT.sub("", s))
    t = PAT_STRING.sub('""', t)
    bal = {c: t.count(c) for c in "{}()[]"}
    lines = s.count("\n") + 1
    total += lines
    ok = bal["{"] == bal["}"] and bal["("] == bal[")"] and bal["["] == bal["]"]
    flag = "" if ok else "  <== 不平衡"
    print(f"{p}: {lines} 行  brace={bal['{']}/{bal['}']} paren={bal['(']}/{bal[')']} bracket={bal['[']}/{bal[']']}{flag}")
print("总行数", total)