"""
Tolerant extraction of a code / data block from an LLM response.

The LLM_* helpers originally did `re.search(r"```(.*?)```", response)` and
returned `None` when the model did not wrap its answer in a fenced block. That
`None` then blew up downstream (`prolit_run.py` line 66
`activities_description.replace(...)`, `eval(None)` in column_entity_approach).
Some models (e.g. openai/gpt-oss-120b) frequently return a bare dict/list with
no fence, which made whole stress-test runs fail.

This falls back through: fenced block -> first `open_ch` .. last `close_ch` ->
the stripped response, so the caller's parser (`ast.literal_eval` / `eval`)
always gets something and raises a clear error if it is genuinely unparseable.
"""

import re

_FENCE_RE = re.compile(r"```[a-zA-Z0-9_.+-]*\s*\n?(.*?)```", re.DOTALL)


def extract_block(response: str, open_ch: str = "{", close_ch: str = "}") -> str:
    if not response:
        return ""
    m = _FENCE_RE.search(response)
    body = m.group(1) if m else response
    i, j = body.find(open_ch), body.rfind(close_ch)
    if i != -1 and j != -1 and j >= i:
        return body[i:j + 1].strip()
    return body.strip()
