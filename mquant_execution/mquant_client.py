"""Read-only HTTP client for the M-quant strategy execution API."""
from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MQuantOffline(RuntimeError):
    pass


class MQuantHTTPError(RuntimeError):
    pass


class MQuantClient:
    """Small compatibility client for the current ``/strategy-api`` routes.

    The M-quant service exposes all three routes as GET endpoints and returns
    JSON directly (catalogs contain a ``strategies`` array; signals are a
    signal.v1 object).  The client deliberately does not turn a failed request
    into a cached/old signal.
    """

    def __init__(self, base_url=None, timeout=8, opener=None, offline=None):
        self.base_url = (base_url or os.getenv('MQUANT_URL', 'http://127.0.0.1:5555')).rstrip('/')
        self.timeout = timeout
        self.opener = opener or urlopen
        self.offline = (
            str(os.getenv('MQUANT_OFFLINE', '')).lower() in ('1', 'true', 'yes', 'on')
            if offline is None else bool(offline)
        )

    def _request(self, method, path, payload=None, query=None):
        if self.offline:
            raise MQuantOffline('MQUANT_OFFLINE')
        url = self.base_url + path
        if query:
            url += '?' + urlencode({key: value for key, value in query.items() if value not in (None, '')})
        body = None
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'mquant-execution/0.1',
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = Request(url, data=body, headers=headers, method=method)
        response = self.opener(request, timeout=self.timeout)
        try:
            status = response.getcode() if hasattr(response, 'getcode') else None
            raw = response.read()
        finally:
            close = getattr(response, 'close', None)
            if close:
                close()
        if status is not None and status >= 400:
            raise MQuantHTTPError(f'mquant_http_{status}:{path}')
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8')
        try:
            return json.loads(raw or '{}')
        except (TypeError, ValueError) as exc:
            raise MQuantHTTPError(f'mquant_invalid_json:{path}') from exc

    def catalog(self):
        return self._request('GET', '/strategy-api/execution-catalog')

    def list_strategies(self):
        return self.catalog()

    def run_once(self, strategy_id, strategy_version='', parameters=None):
        if not strategy_id:
            raise ValueError('strategy_id_required')
        # execution-signal is intentionally GET-only in the current M-quant
        # server.  Version/parameters remain client-side activation metadata.
        return self._request('GET', '/strategy-api/execution-signal', query={'strategy': strategy_id})

    def run_strategy_once(self, strategy_id, strategy_version='', parameters=None):
        return self.run_once(strategy_id, strategy_version, parameters)

    def health_details(self):
        if self.offline:
            return {'reachable': False, 'offline': True, 'error': 'MQUANT_OFFLINE'}
        try:
            payload = self._request('GET', '/strategy-api/execution-health')
            return {'reachable': True, 'offline': False, 'error': None, 'response': payload}
        except Exception as exc:
            return {'reachable': False, 'offline': False, 'error': str(exc)}

    def health(self):
        details = self.health_details()
        return {key: details[key] for key in ('reachable', 'offline', 'error')}
