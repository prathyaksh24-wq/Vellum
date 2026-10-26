"""Readable nested field projection shared by MCP change reviews."""
import re


def review_fields(arguments):
    """Show nested record fields as labeled values, rather than raw tool JSON."""
    result = []

    def label(key):
        return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(key)).replace("_", " ").capitalize()

    def visit(value, path):
        if isinstance(value, dict) and value:
            for key, item in value.items():
                visit(item, path + [label(key)])
        elif isinstance(value, list) and value:
            for index, item in enumerate(value, 1):
                visit(item, path + [str(index)])
        else:
            rendered = ("None" if value is None else "Yes" if value is True else "No" if value is False
                        else "Empty" if isinstance(value, (dict, list)) else str(value))
            result.append({"label": " · ".join(path), "value": rendered})

    for key, value in arguments.items():
        visit(value, [label(key)])
    return result
