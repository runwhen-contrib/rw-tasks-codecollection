"""Count the characters in `text` -- a minimal task fixture for rw-task's
bundle-host smoke tests, not a real, useful capability."""


def main(ctx, text: str):
    return {"length": {"count": len(text)}}
