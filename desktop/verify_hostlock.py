"""Manual verification harness for the elected-host protocol in hostlock.py.

Runs real OS processes against one local shared folder (standing in for the
network share) — no Django, no PyInstaller needed. Exercises exactly the
scenarios called out in the desktop-build plan's verification section.

Usage: python desktop/verify_hostlock.py
"""
import json
import multiprocessing
import os
import shutil
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import hostlock  # noqa: E402

PORT = 8421


def _serve_stub(claim, ready_evt, stop_evt):
    """Minimal stand-in for the real /__desktop_ping__/ Django view."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/__desktop_ping__/':
                body = json.dumps({'pid': claim.pid, 'epoch': claim.epoch, 'started_at': claim.started_at}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *a):
            pass

    server = HTTPServer(('0.0.0.0', claim.port), Handler)
    server.timeout = 0.5
    ready_evt.set()
    while not stop_evt.is_set():
        server.handle_request()
    server.server_close()


def run_instance(data_dir, port, tag, result_q, hold_seconds, suspend_after=None):
    """One 'PC opening the shared folder'. Elects, reports what it became,
    and if host, serves + heartbeats for hold_seconds (or until suspended)."""
    try:
        outcome = hostlock.elect(Path(data_dir), port, max_attempts=40)
    except Exception as e:  # noqa: BLE001
        result_q.put((tag, 'error', str(e)))
        return

    if isinstance(outcome, hostlock.ClientInfo):
        result_q.put((tag, 'client', outcome.url))
        return

    claim = outcome
    result_q.put((tag, 'host', claim.epoch))

    ready = multiprocessing.Event()
    stop = multiprocessing.Event()
    import threading
    t = threading.Thread(target=_serve_stub, args=(claim, ready, stop), daemon=True)
    t.start()
    ready.wait(timeout=2)

    if suspend_after is not None:
        time.sleep(suspend_after)
        result_q.put((tag, 'suspending', None))
        # multiprocessing.Queue.put() only buffers the item; a background
        # feeder thread actually writes it to the pipe. SIGSTOP freezes
        # every thread in this process immediately, including that feeder
        # thread, so without a pause here the parent would never see the
        # message until we're resumed. Give the feeder thread a scheduling
        # window to actually flush it first.
        time.sleep(0.3)
        os.kill(os.getpid(), signal.SIGSTOP)
        # Resumes here once SIGCONT'd by the parent test process.
        ok = claim.heartbeat_once()
        result_q.put((tag, 'post-resume-heartbeat-ok' if ok else 'post-resume-evicted', claim.epoch))
        stop.set()
        return

    deadline = time.monotonic() + hold_seconds
    while time.monotonic() < deadline and not claim.is_evicted:
        if not claim.heartbeat_once():
            break
        time.sleep(hostlock.HEARTBEAT_INTERVAL)
    stop.set()
    claim.release()
    result_q.put((tag, 'host-done', None))


def fresh_dir(name):
    d = Path('/tmp') / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return str(d)


def test_basic_election():
    print('\n=== Test 1: two instances, one host one client ===')
    data_dir = fresh_dir('msv_hostlock_t1')
    q = multiprocessing.Queue()
    p1 = multiprocessing.Process(target=run_instance, args=(data_dir, PORT, 'A', q, 3))
    p2 = multiprocessing.Process(target=run_instance, args=(data_dir, PORT, 'B', q, 3))
    p1.start()
    time.sleep(0.5)
    p2.start()
    p1.join(10)
    p2.join(10)

    results = {}
    while not q.empty():
        tag, kind, extra = q.get()
        results.setdefault(tag, []).append((kind, extra))
    print('results:', results)
    roles = [kind for tag in results for kind, _ in results[tag] if kind in ('host', 'client')]
    assert sorted(roles) == ['client', 'host'], f'expected exactly one host and one client, got {roles}'
    print('PASS: exactly one host, one client, client successfully pinged host')


def test_crash_takeover():
    print('\n=== Test 2: SIGKILL host mid-run -> takeover with bumped epoch ===')
    data_dir = fresh_dir('msv_hostlock_t2')
    q = multiprocessing.Queue()
    p1 = multiprocessing.Process(target=run_instance, args=(data_dir, PORT, 'A', q, 60))
    p1.start()

    # Wait for A to actually become host.
    tag, kind, epoch1 = q.get(timeout=10)
    assert kind == 'host', kind
    print(f'{tag} is host, epoch={epoch1}')

    time.sleep(1)
    os.kill(p1.pid, signal.SIGKILL)
    p1.join(5)
    print('killed host A without cleanup')

    q2 = multiprocessing.Queue()
    p2 = multiprocessing.Process(target=run_instance, args=(data_dir, PORT, 'B', q2, 3))
    p2.start()
    tag, kind, epoch2 = q2.get(timeout=30)
    p2.join(10)
    assert kind == 'host', f'expected B to take over as host, got {kind}'
    assert epoch2 > epoch1, f'expected epoch to increase past {epoch1}, got {epoch2}'
    print(f'PASS: {tag} took over as host, epoch {epoch1} -> {epoch2}')


def test_split_brain_fencing():
    print('\n=== Test 3: SIGSTOP host (alive-but-frozen) -> takeover -> resumed host self-evicts ===')
    data_dir = fresh_dir('msv_hostlock_t3')
    q = multiprocessing.Queue()
    p1 = multiprocessing.Process(target=run_instance, args=(data_dir, PORT, 'A', q, 999, 2))
    p1.start()

    tag, kind, epoch1 = q.get(timeout=10)
    assert kind == 'host', kind
    print(f'{tag} is host, epoch={epoch1}')

    tag, kind, _ = q.get(timeout=10)
    assert kind == 'suspending', kind
    time.sleep(hostlock.STALE_AFTER + 3)  # let A actually hit SIGSTOP and go stale
    print('A should be SIGSTOP-frozen by now (not dead, just unresponsive)')

    q2 = multiprocessing.Queue()
    p2 = multiprocessing.Process(target=run_instance, args=(data_dir, PORT, 'B', q2, 3))
    p2.start()
    tag2, kind2, epoch2 = q2.get(timeout=30)
    p2.join(10)
    assert kind2 == 'host', f'expected B to take over while A is frozen, got {kind2}'
    assert epoch2 > epoch1
    print(f'B took over as new host while A was frozen, epoch {epoch1} -> {epoch2}')

    os.kill(p1.pid, signal.SIGCONT)
    print('resumed A — it must notice it has been evicted and stop, not keep serving')
    tag, kind, epoch_seen = q.get(timeout=10)
    p1.join(10)
    assert kind == 'post-resume-evicted', f'SPLIT BRAIN: A thought it was still host after resuming! got {kind}'
    print(f'PASS: resumed A ({tag}) correctly detected eviction (its own epoch was {epoch_seen}) and self-terminated')


if __name__ == '__main__':
    test_basic_election()
    test_crash_takeover()
    test_split_brain_fencing()
    print('\nAll hostlock protocol tests passed.')
