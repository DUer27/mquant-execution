"""Optional background PAPER market refresh scheduler."""
from __future__ import annotations
import threading, time
from .market_service import MarketService
class MarketScheduler:
    def __init__(self, service, symbols, interval=30):
        self.service, self.symbols, self.interval = service, list(symbols), interval
        self._stop=threading.Event(); self._thread=None
    def start(self):
        if self._thread and self._thread.is_alive(): return self
        self._stop.clear(); self._thread=threading.Thread(target=self._run,daemon=True); self._thread.start(); return self
    def _run(self):
        while not self._stop.is_set():
            try: self.service.refresh(self.symbols, 'scheduler:' + ','.join(sorted(self.symbols)) + ':' + str(int(time.time() // self.interval)))
            except Exception: pass
            self._stop.wait(self.interval)
    def stop(self): self._stop.set(); self._thread and self._thread.join(timeout=self.interval+1)
