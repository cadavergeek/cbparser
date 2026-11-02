import json
import re


def encode_config_value(value: str) -> str:
    return "json:" + json.dumps(value, ensure_ascii=False)


def decode_config_value(value: str) -> str:
    if value.startswith("json:"):
        try:
            return json.loads(value[5:])
        except json.JSONDecodeError:
            return value
    return value


def clean_response(text: str) -> str:
    text = re.sub(r"```[a-zA-Z0-9]*\n?", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`([^`\n]*)`", r"\1", text)
    text = text.replace("`", "")
    text = re.sub(r"\(Returning\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(
        r"^name\s*,\s*level\s*,\s*rank\s*,\s*x\s*,\s*y\s*,\s*time.*$",
        "", text, flags=re.IGNORECASE | re.MULTILINE,
    )
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
