"""Synthetic reducer with a deliberate non-determinism bug (wall-clock read) for the replaycheck demo."""
import time

def initial():
    return {"n": 0}

def apply(state, event):
    return {"n": state["n"] + 1, "stamped_at": time.time()}
