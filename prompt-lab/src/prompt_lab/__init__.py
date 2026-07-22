"""prompt-lab: a CLI lab for testing RAG prompts against OpenAI-compatible providers."""

import sys

__version__ = "0.1.0"

# Windows consoles may default to a legacy codepage (e.g. cp1252) that cannot
# render Persian text. Force UTF-8 on the std streams before rich creates
# its Console objects.
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
