from __future__ import annotations

import threading
import time


class MarketScheduler:
    """Background polling loop for PAPER market quotes.

    ``symbols`` may be a fixed iterable or a callable returning the current
    symbol set. The scheduler never submits orders; source failures are stored
    by MarketService and remain visible through its status API.
    """

    def __init__(self, service, symbols, interval=30):
        self.service, self.symbols, self.interval = service, symbols, max(1, int(interval))
        self._stop = threading.Event()
        self._thread = None

    def _current_symbols(self):
        value = self.symbols() if callable(self.symbols) else self.symbols
        return sorted({str(symbol).strip() for symbol in (value or []) if str(symbol).strip()})

    def start(self):
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='paper-market-poller', daemon=True)
        self._thread.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            symbols = self._current_symbols()
            if symbols:
                try:
                    bucket = int(time.time() // self.interval)
                    key = 'scheduler:' + ','.join(symbols) + ':' + str(bucket)
                    self.service.refresh(symbols, key)
                except Exception:
                    # MarketService has already persisted SOURCE_ERROR for
                    # source failures; the next interval remains available.
                    pass
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 1)
