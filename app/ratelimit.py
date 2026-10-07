"""Ograniczanie liczby żądań i ochrona logowania przed zgadywaniem haseł.

Liczniki trzymane są w pamięci procesu (okno przesuwne). To wystarcza dla jednej instancji API;
przy wielu instancjach trzeba je przenieść do współdzielonego magazynu (np. Redis).
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    enabled: bool = True
    api_per_minute: int = 300  # wszystkie żądania z jednego adresu IP
    auth_per_minute: int = 20  # logowanie i rejestracja z jednego adresu IP
    login_max_failures: int = 5  # nieudane logowania na jedno konto (z jednego IP)
    login_window_seconds: int = 900  # okno liczenia porażek i czas blokady


class SlidingWindow:
    """Zlicza zdarzenia na klucz w oknie czasowym."""

    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window
        self.clock = clock
        self._events: dict[str, deque[float]] = {}

    def _trim(self, key: str) -> deque[float]:
        events = self._events.setdefault(key, deque())
        cutoff = self.clock() - self.window
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            self._events.pop(key, None)
            return deque()
        return events

    def retry_after(self, key: str) -> int:
        """Ile sekund zostało do zwolnienia klucza; 0, gdy limit nie jest przekroczony."""
        events = self._trim(key)
        if len(events) < self.limit:
            return 0
        return max(1, int(events[0] + self.window - self.clock()) + 1)

    def hit(self, key: str) -> int:
        """Rejestruje zdarzenie. Zwraca 0, gdy mieści się w limicie, inaczej czas oczekiwania w sekundach."""
        wait = self.retry_after(key)
        if wait:
            return wait
        self._events.setdefault(key, deque()).append(self.clock())
        return 0

    def add(self, key: str) -> None:
        """Rejestruje zdarzenie bez sprawdzania limitu (np. nieudane logowanie)."""
        self._trim(key)
        self._events.setdefault(key, deque()).append(self.clock())

    def reset(self, key: str) -> None:
        self._events.pop(key, None)


class RateLimiter:
    def __init__(self, limits: Limits, clock: Callable[[], float] = time.monotonic):
        self.limits = limits
        self.api = SlidingWindow(limits.api_per_minute, 60, clock)
        self.auth = SlidingWindow(limits.auth_per_minute, 60, clock)
        self.failures = SlidingWindow(limits.login_max_failures, limits.login_window_seconds, clock)

    def check_api(self, ip: str) -> int:
        return self.api.hit(ip) if self.limits.enabled else 0

    def check_auth(self, ip: str) -> int:
        return self.auth.hit(ip) if self.limits.enabled else 0

    @staticmethod
    def _login_key(ip: str, email: str) -> str:
        return f"{ip}|{email.lower()}"

    def login_blocked(self, ip: str, email: str) -> int:
        """Sekundy blokady logowania na to konto z tego IP (0 = wolno próbować)."""
        if not self.limits.enabled:
            return 0
        return self.failures.retry_after(self._login_key(ip, email))

    def login_failed(self, ip: str, email: str) -> None:
        if self.limits.enabled:
            self.failures.add(self._login_key(ip, email))

    def login_succeeded(self, ip: str, email: str) -> None:
        self.failures.reset(self._login_key(ip, email))
