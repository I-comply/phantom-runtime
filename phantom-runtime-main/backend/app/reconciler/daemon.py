import logging
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional, Protocol

from .replica import Replica, digest_of
from .vclock import Ordering, VectorClock, consensus

log = logging.getLogger("phantom.reconciler")


class PeerError(Exception):
    """Peer unreachable (timeout, refused, partitioned)."""


class Peer(Protocol):
    node_id: str

    def status(self) -> Dict:
        """Return {"clock": {...}, "digest": str}. Raise PeerError if unreachable."""

    def snapshot(self) -> Dict:
        """Return the full replica snapshot. Raise PeerError if unreachable."""


class DriftKind(str, Enum):
    LOCAL_BEHIND = "local_behind"      # peer clock dominates ours
    LOCAL_AHEAD = "local_ahead"        # our clock dominates peer's
    CONCURRENT = "concurrent"          # divergent histories (partition)
    CORRUPT = "corrupt"                # clocks equal, hashes differ: state damage or non-deterministic writes


@dataclass
class DriftEvent:
    peer: str
    kind: DriftKind
    healed_partition: bool
    merged: bool
    consensus_clock: Dict[str, int]


class ReconcilerDaemon:
    """Each tick: probe peers, compare (clock, state hash) against the consensus clock, merge on drift.

    A peer that was unreachable and responds again is a healed partition: it is always merged,
    regardless of what the cheap status comparison says.
    """

    def __init__(self, replica: Replica, peers: List[Peer], interval: float = 5.0,
                 on_event: Optional[Callable[[DriftEvent], None]] = None):
        self.replica, self.peers, self.interval, self.on_event = replica, peers, interval, on_event
        self._down: Dict[str, bool] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.consensus_clock = VectorClock()

    def tick(self) -> List[DriftEvent]:
        statuses = {}
        for p in self.peers:
            try:
                statuses[p.node_id] = p.status()
            except PeerError:
                self._down[p.node_id] = True
        self.consensus_clock = consensus(
            [self.replica.clock] + [VectorClock.from_dict(s["clock"]) for s in statuses.values()])

        events = []
        for p in self.peers:
            st = statuses.get(p.node_id)
            if st is None:
                continue
            healed = self._down.pop(p.node_id, False)
            peer_clock = VectorClock.from_dict(st["clock"])
            order = self.replica.clock.compare(peer_clock)
            same_hash = st["digest"] == self.replica.digest()
            if same_hash and order == Ordering.EQUAL and not healed:
                continue
            if same_hash and not healed:
                continue  # clocks differ only in already-merged history; states agree
            kind = {Ordering.BEFORE: DriftKind.LOCAL_BEHIND, Ordering.AFTER: DriftKind.LOCAL_AHEAD,
                    Ordering.CONCURRENT: DriftKind.CONCURRENT,
                    Ordering.EQUAL: DriftKind.CORRUPT}[order]
            merged = False
            try:
                snap = p.snapshot()
                self.replica.merge_snapshot(snap)
                merged = True
            except PeerError:
                self._down[p.node_id] = True
            except (ValueError, KeyError, TypeError) as e:
                log.error("rejecting snapshot from %s: %s", p.node_id, e)
            ev = DriftEvent(p.node_id, kind, healed, merged, self.consensus_clock.to_dict())
            log.warning("drift %s", ev)
            events.append(ev)
            if self.on_event:
                self.on_event(ev)
        return events

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="reconciler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("reconcile tick failed")
            self._stop.wait(self.interval)


def peer_status(replica: Replica) -> Dict:
    """Helper for serving the Peer.status contract from a local replica."""
    snap = replica.snapshot()
    return {"clock": snap["clock"], "digest": digest_of(snap["objects"])}
