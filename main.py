from __future__ import annotations

import sys

from screen_airdrop.sender.legacy import main as sender_legacy_main
from screen_airdrop.sender.modern import main as sender_main

from screen_airdrop.receiver.cli import main as receiver_main


def _usage() -> int:
    print(
        "Usage:\n"
        "  python main.py sender <args...>\n"
        "  python main.py receiver <args...>\n"
        "  python main.py sender-legacy <args...>"
    )
    return 2


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _usage()

    cmd = args[0].strip().lower()
    rest = args[1:]
    if cmd == "sender":
        return int(sender_main(rest))
    if cmd == "receiver":
        return int(receiver_main(rest))
    if cmd in ("sender-legacy", "legacy-sender", "legacy"):
        return int(sender_legacy_main(rest))
    return _usage()


if __name__ == "__main__":
    raise SystemExit(main())
