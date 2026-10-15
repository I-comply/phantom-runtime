"""Child process: fold events with a perturbed clock/RNG/uuid. Hash seed is set by the parent via
PYTHONHASHSEED. Reads {"reducer","events","run_id","dump_at"} from stdin, writes JSON to stdout."""
import json, sys


def perturb(run_id):
    import datetime, random, time, uuid
    rnd = random.Random(run_id * 7919 + 13)
    random.seed(run_id * 104729 + 1)
    base = 1_700_000_000 + run_id * 3_196_800 + rnd.randrange(10 ** 6)
    tick = [0]

    def fake():
        tick[0] += 1
        return base + tick[0] * 0.001 * (run_id + 1)

    time.time, time.monotonic, time.perf_counter = fake, fake, fake
    time.time_ns = lambda: int(fake() * 1e9)
    real = datetime.datetime

    class DT(real):
        @classmethod
        def now(cls, tz=None):
            return real.fromtimestamp(fake(), tz)

        @classmethod
        def utcnow(cls):
            return real.fromtimestamp(fake(), datetime.timezone.utc).replace(tzinfo=None)

    datetime.datetime = DT
    uuid.uuid4 = lambda: uuid.UUID(int=rnd.getrandbits(128), version=4)


def main():
    req = json.loads(sys.stdin.read())
    perturb(req["run_id"])
    from .util import load_module, digest, norm
    mod = load_module(req["reducer"])
    digests, state, dump = [], mod.initial(), None
    try:
        for i, ev in enumerate(req["events"], 1):
            state = mod.apply(state, ev)
            digests.append(digest(state))
            if req.get("dump_at") == i:
                dump = norm(state)
    except Exception as e:  # reported by the parent as a finding
        json.dump({"error": "%s: %s" % (type(e).__name__, e), "at": len(digests) + 1, "digests": digests}, sys.stdout)
        return
    json.dump({"digests": digests, "dump": dump}, sys.stdout)


if __name__ == "__main__":
    main()
