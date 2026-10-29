import asyncio
import logging
import os
import sys
import threading
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Final

from baseline_adapter.channel import Channel

# The conformance project's file, whose version the hello gives as the baseline's.
PROJECT_FILE: Final = Path(__file__).resolve().parents[1] / "pyproject.toml"


def main() -> None:
    """Speak the adapter protocol on stdin and stdout until stdin ends, then exit."""
    channel = Channel.take_stdout()
    logging.basicConfig(format="%(name)s: %(levelname)s: %(message)s")
    # Imported once stdout is the channel's, so whatever the clients print as they
    # load is a diagnostic.
    from baseline_adapter.adapter import Adapter, hello

    project = tomllib.loads(PROJECT_FILE.read_text(encoding="utf-8"))
    version: str = project["project"]["version"]
    channel.write(hello(version))
    asyncio.run(_serve(Adapter(channel).dispatch))


async def _serve(dispatch: Callable[[bytes], None]) -> None:
    loop = asyncio.get_running_loop()
    # A thread of its own, since asyncio can't read an anonymous pipe on Windows.
    reader = threading.Thread(
        target=_read_commands, args=(loop, dispatch), name="stdin", daemon=True
    )
    reader.start()
    await loop.create_future()


def _read_commands(
    loop: asyncio.AbstractEventLoop, dispatch: Callable[[bytes], None]
) -> None:
    try:
        for line in sys.stdin.buffer:
            loop.call_soon_threadsafe(dispatch, line)
    finally:
        loop.call_soon_threadsafe(_end)


def _end() -> None:
    sys.stderr.flush()
    # Not asyncio.run's teardown, which would wait on the calls under way and close
    # what they opened, where the runner closes first what a case needs closed.
    os._exit(0)


if __name__ == "__main__":
    main()
