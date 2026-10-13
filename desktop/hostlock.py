"""Elected-host coordination for the portable desktop build.

Multiple PCs can open the same shared folder at once. Exactly one of them
must run the Django server and touch db.sqlite3 at any moment — everyone
else is a pure HTTP client. Coordination happens ONLY through a lock file
inside the shared folder (``desktop_state/host.lock``): local TCP port
binding does NOT give cross-machine exclusion, since two different PCs can
each bind their own port 8420 independently without knowing about each
other.

Protocol
--------
- Claim: create ``host.lock`` with an exclusive-create open (fails if it
  already exists). This is a genuine atomic op on SMB, the same primitive
  Windows itself relies on for file locking.
- Fencing: a heartbeat-age check alone can cause split-brain — a host that
  is merely asleep/stalled (not dead) looks "stale" to others, and if a
  second instance takes over while the first is still actually running,
  both would write the SQLite file at once. ``epoch`` is a monotonically
  increasing integer; a takeover increments it. The host's own heartbeat
  loop reads the lock back after every write and checks its own
  ``pid``+``epoch`` are still the ones on disk — if not, something else
  has claimed the lock, and it must stop serving immediately rather than
  keep running.
- Staleness is measured on the *observer's own clock* ("how long have I
  personally not seen this heartbeat value change"), never by comparing
  the host's embedded timestamp against the reader's wall clock — office
  PCs without a domain controller commonly have clock drift of more than
  the staleness window.
- All lock writes are write-to-temp-file + ``os.replace()``, never an
  in-place edit, so a peer reading over the network never sees a
  half-written JSON blob.
"""
from __future__ import annotations

import json
import os
import random
import socket
import tempfile
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

LOCK_FILENAME = 'host.lock'
HEARTBEAT_INTERVAL = 5.0
STALE_AFTER = 15.0  # observer-measured seconds since the heartbeat last changed
PING_TIMEOUT = 1.5


def get_lan_ip() -> str:
    """This machine's real LAN-facing IP, without needing actual internet
    access (the UDP socket is never sent on, only used to ask the OS which
    local interface it would route through)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


def _atomic_write(path: Path, data: dict) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix='.host.lock.')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_lock(path: Path) -> Optional[dict]:
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return None


def _ping(host_ip: str, port: int) -> Optional[dict]:
    url = f'http://{host_ip}:{port}/__desktop_ping__/'
    try:
        with urllib.request.urlopen(url, timeout=PING_TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


@dataclass
class HostClaim:
    """Returned when this process becomes the host. Call `release()` on
    clean shutdown; call `heartbeat_once()` periodically (or start
    `start_heartbeat_thread`) to prove liveness and detect eviction."""
    lock_path: Path
    host_ip: str
    port: int
    pid: int
    hostname: str
    started_at: float
    epoch: int
    _evicted: threading.Event = None  # type: ignore[assignment]

    def __post_init__(self):
        self._evicted = threading.Event()

    def _write(self, heartbeat: float) -> None:
        _atomic_write(self.lock_path, {
            'host_ip': self.host_ip,
            'port': self.port,
            'pid': self.pid,
            'hostname': self.hostname,
            'started_at': self.started_at,
            'epoch': self.epoch,
            'heartbeat': heartbeat,
        })

    def heartbeat_once(self) -> bool:
        """Check the lock is still ours BEFORE writing a fresh heartbeat —
        never the other way around. Writing first and checking after would
        let a resumed, previously-evicted host silently clobber whatever
        the new legitimate host had just written, undoing the whole point
        of fencing. Returns False (and sets `is_evicted`) the moment this
        process should stop serving."""
        if self._evicted.is_set():
            return False
        on_disk = _read_lock(self.lock_path)
        if not on_disk or on_disk.get('pid') != self.pid or on_disk.get('epoch') != self.epoch:
            self._evicted.set()
            return False
        self._write(time.time())
        return True

    @property
    def is_evicted(self) -> bool:
        return self._evicted.is_set()

    def start_heartbeat_thread(self) -> threading.Thread:
        def _loop():
            while not self._evicted.is_set():
                self.heartbeat_once()
                time.sleep(HEARTBEAT_INTERVAL)
        t = threading.Thread(target=_loop, name='host-heartbeat', daemon=True)
        t.start()
        return t

    def release(self) -> None:
        """Clean shutdown: drop the lock so the next launch doesn't have to
        wait out the staleness window."""
        self._evicted.set()
        try:
            on_disk = _read_lock(self.lock_path)
            if on_disk and on_disk.get('pid') == self.pid and on_disk.get('epoch') == self.epoch:
                os.unlink(self.lock_path)
        except OSError:
            pass


@dataclass
class ClientInfo:
    host_ip: str
    port: int

    @property
    def url(self) -> str:
        return f'http://{self.host_ip}:{self.port}/'


def elect(data_dir: Path, port: int, max_attempts: int = 8) -> 'HostClaim | ClientInfo':
    """Run the full election protocol and return either a HostClaim (this
    process is now the host — caller must start serving on `port`) or a
    ClientInfo (someone else is already serving — caller should just open a
    window pointed at `.url`)."""
    state_dir = data_dir / 'desktop_state'
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / LOCK_FILENAME

    last_seen_heartbeat: Optional[float] = None
    last_seen_at = time.monotonic()

    for attempt in range(max_attempts):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            claim = HostClaim(
                lock_path=lock_path,
                host_ip=get_lan_ip(),
                port=port,
                pid=os.getpid(),
                hostname=socket.gethostname(),
                started_at=time.time(),
                epoch=_next_epoch(lock_path),
            )
            claim._write(time.time())
            return claim
        except FileExistsError:
            pass

        existing = _read_lock(lock_path)
        if existing:
            alive = _ping(existing.get('host_ip', ''), existing.get('port', port))
            if alive:
                return ClientInfo(host_ip=existing['host_ip'], port=existing['port'])

            hb = existing.get('heartbeat')
            now = time.monotonic()
            if hb != last_seen_heartbeat:
                last_seen_heartbeat = hb
                last_seen_at = now
            elif now - last_seen_at >= STALE_AFTER:
                # Dead (not just unresponsive — _ping already failed above).
                # Remove the stale lock and immediately try to claim it with
                # an incremented epoch, in the same breath, so the window
                # where the lock doesn't exist is as small as possible. If a
                # concurrent challenger wins that exact race, our create
                # just fails and we fall through to retry as a normal
                # contention case.
                try:
                    os.unlink(lock_path)
                except OSError:
                    pass
                try:
                    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.close(fd)
                    claim = HostClaim(
                        lock_path=lock_path,
                        host_ip=get_lan_ip(),
                        port=port,
                        pid=os.getpid(),
                        hostname=socket.gethostname(),
                        started_at=time.time(),
                        epoch=int(existing.get('epoch', 0)) + 1,
                    )
                    claim._write(time.time())
                    return claim
                except FileExistsError:
                    pass
                last_seen_heartbeat = None
                last_seen_at = time.monotonic()

        time.sleep(0.3 + random.random() * 0.7)

    raise RuntimeError('Could not elect a host or find a live one after %d attempts' % max_attempts)


def _next_epoch(lock_path: Path) -> int:
    prev = _read_lock(lock_path) or {}
    return int(prev.get('epoch', 0)) + 1
