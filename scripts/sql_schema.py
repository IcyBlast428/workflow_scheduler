"""SQL file parser for the fresh schema initializer and checks."""

import re


def statements(path):
    content = path.read_text(encoding="utf-8")
    result, current, quote, index = [], [], "", 0
    while index < len(content):
        if quote:
            if content.startswith(quote, index):
                current.append(quote)
                index += len(quote)
                if quote in ("'", '"') and content.startswith(quote, index):
                    current.append(quote)
                    index += len(quote)
                else:
                    quote = ""
            else:
                current.append(content[index])
                index += 1
            continue
        if content.startswith("--", index):
            end = content.find("\n", index)
            index = len(content) if end < 0 else end
            continue
        if content.startswith("/*", index):
            end = content.find("*/", index + 2)
            if end < 0:
                raise ValueError("unclosed SQL comment")
            current.append(" ")
            index = end + 2
            continue
        char = content[index]
        dollar = (
            re.match(r"\$[A-Za-z0-9_]*\$", content[index:]) if char == "$" else None
        )
        if char in ("'", '"') or dollar:
            quote = dollar.group() if dollar else char
            current.append(quote)
            index += len(quote)
        elif char == ";":
            if "".join(current).strip():
                result.append("".join(current).strip())
            current = []
            index += 1
        else:
            current.append(char)
            index += 1
    if quote:
        raise ValueError("unclosed SQL literal")
    if "".join(current).strip():
        result.append("".join(current).strip())
    return result
