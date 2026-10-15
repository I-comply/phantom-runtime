from typing import Dict, Any, List
from app.core.models import Event
from app.core.reconstructor_v2 import StateReconstructorV2


class StateReconstructor(StateReconstructorV2):
    """Deprecated alias kept for imports. There is one reconstructor: StateReconstructorV2.

    The old v1 implementation had no apply_event (so snapshot + incremental replay raised
    AttributeError) and produced different state for DeFi events than the V2 path used by
    /api/state, so a state served from a snapshot could differ from a full replay."""
