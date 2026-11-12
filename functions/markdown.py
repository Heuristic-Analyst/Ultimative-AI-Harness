# markdown.py — turns markdown (what the model writes: **bold**, # headings, - lists, ``` code ```) into pieces the
# window can draw. it draws nothing itself, and knows nothing about tkinter: it only says WHAT each piece of text is.
#
#   parse("# Hi\nsome **bold** text")  ->  [("Hi\n", ("h1",), None),
#                                           ("some ", (), None), ("bold", ("bold",), None), (" text\n", (), None)]
#
# each piece is (text, tags, link): tags name the looks (gui.py decides what "bold" or "h1" looks like), link is the
# address of a link, or None. it also works on half a text, which is what the window has while an answer streams in:
# a code block that isn't closed yet is simply shown as code up to where it is.
#
# what it knows:  # ## ### headings · **bold** · *italic* · `code` · [text](https://link) · - * + and 1. lists (also
# indented) · > quotes · ``` code blocks ``` · --- lines · | tables |

import re

# the marks inside a line, tried from left to right at each position:  `code`  **bold**  __bold__  *italic*  _italic_
# [text](link)
INLINE = re.compile(r"(`+)(.+?)\1"
                    r"|\*\*(?=\S)(.+?)(?<=\S)\*\*"
                    r"|__(?=\S)(.+?)(?<=\S)__"
                    r"|\*(?=\S)(.+?)(?<=\S)\*"
                    r"|(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)"
                    r"|\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
HEADING = re.compile(r"(#{1,6})\s+(.*)")
BULLET = re.compile(r"(\s*)[-*+]\s+(.*)")
NUMBER = re.compile(r"(\s*)(\d+)[.)]\s+(.*)")
RULE = re.compile(r"\s*([-*_])(\s*\1){2,}\s*")          # --- or *** or ___ : a line across
TABLE_LINE = re.compile(r"\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*")   # |---|---| : under a table's head


def inline(text, tags=()):
    """one line's text as pieces: plain text keeps `tags`, marked text gets its own tag added"""
    pieces = []
    position = 0
    for found in INLINE.finditer(text):
        if found.start() > position:                     # the plain text before this mark
            pieces.append((text[position:found.start()], tags, None))
        if found.group(2) is not None:                   # `code`: shown as it is, nothing inside it is a mark
            pieces.append((found.group(2), tags + ("code",), None))
        elif found.group(3) is not None or found.group(4) is not None:   # **bold** or __bold__
            pieces += inline(found.group(3) or found.group(4), tags + ("bold",))   # may have marks inside
        elif found.group(5) is not None or found.group(6) is not None:   # *italic* or _italic_
            pieces += inline(found.group(5) or found.group(6), tags + ("italic",))
        else:                                            # [text](link)
            pieces.append((found.group(7), tags + ("link",), found.group(8)))
        position = found.end()
    if position < len(text):                             # the plain text after the last mark
        pieces.append((text[position:], tags, None))
    return pieces


def cells_of(line):
    """the cells of one table line: "| a | b |" -> ["a", "b"]"""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def plain(text):
    """a text without its marks, for table cells (they are drawn in one font, to line up)"""
    return "".join(piece[0] for piece in inline(text))


def table(rows):
    """a table as lines of text in one fixed-width font, the columns lined up. the first row is the head"""
    rows = [[plain(cell) for cell in row] for row in rows]
    columns = max(len(row) for row in rows)
    rows = [row + [""] * (columns - len(row)) for row in rows]          # every row as long as the longest
    widths = [max(len(row[c]) for row in rows) for c in range(columns)]
    pieces = []
    for number, row in enumerate(rows):
        line = "   ".join(cell.ljust(widths[c]) for c, cell in enumerate(row)).rstrip()
        pieces.append((line + "\n", ("table", "bold") if number == 0 else ("table",), None))
        if number == 0:                                  # a line under the head
            pieces.append(("   ".join("─" * width for width in widths) + "\n", ("table",), None))
    return pieces


def parse(markdown):
    """the whole text as pieces: (text, tags, link). every line of the text ends with "\\n" in the pieces"""
    pieces = []
    lines = markdown.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):                   # a code block: everything up to the next ``` (or to the
            code = []                                    # end, while the answer is still streaming in)
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1                                       # the closing ```
            pieces.append(("\n".join(code) + "\n", ("codeblock",), None))
            continue

        if "|" in line and i + 1 < len(lines) and "|" in lines[i + 1] and TABLE_LINE.fullmatch(lines[i + 1]):
            rows = [cells_of(line)]                      # a table: its head, the |---| line, then its rows
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(cells_of(lines[i]))
                i += 1
            pieces += table(rows)
            continue

        heading = HEADING.fullmatch(stripped)
        bullet = BULLET.fullmatch(line)
        number = NUMBER.fullmatch(line)
        if not stripped:                                 # an empty line: a small gap
            pieces.append(("\n", ("gap",), None))
        elif RULE.fullmatch(line):                       # --- : a line across. (before the lists: "* * *" is one)
            pieces.append(("\n", ("rule",), None))
        elif heading:
            level = "h" + str(min(len(heading.group(1)), 3))             # #### and deeper look like ###
            pieces += inline(heading.group(2), (level,)) + [("\n", (level,), None)]
        elif bullet or number:
            found = bullet or number
            depth = "list" + str(min(len(found.group(1)) // 2, 2) + 1)   # 2 spaces deeper = one level in. 3 levels
            mark = "•  " if bullet else number.group(2) + ".  "
            pieces += [(mark, (depth,), None)] + inline(found.groups()[-1], (depth,)) + [("\n", (depth,), None)]
        elif stripped.startswith(">"):
            pieces += inline(stripped[1:].strip(), ("quote",)) + [("\n", ("quote",), None)]
        else:                                            # a normal line of text
            pieces += inline(line) + [("\n", (), None)]
        i += 1
    return pieces
