"""Project configuration (.phantomkit.yml / .json) with defaults and env overrides."""
from __future__ import annotations

import copy
import json
import os

from . import yamlite

NAMES = (".phantomkit.yml", ".phantomkit.yaml", ".phantomkit.json")

DEFAULTS = {
    "scan": {
        "rules": ["default"],
        "exclude": [],
        "include": [],
        "fail-on": "error",
        "max-file-size": 1000000,
        "timeout": 30,
        "jobs": 0,
        "baseline": None,
        "require-suppress-reason": False,
        "secrets": {"enabled": True, "allow-paths": [], "allow-regex": [], "disable": []},
        "disable-rules": [],
    },
    "pkg": {
        "registry": "https://registry.npmjs.org/",
        "scopes": {},
        "allowed-registries": [],
        "internal-packages": [],
        "min-release-age-days": 0,
        "ignore-scripts": False,
        "allow-scripts": [],
        "deny-licenses": [],
        "allow-licenses": [],
        "typosquat": "warn",
        "legacy-peer-deps": False,
        "strict-peer-deps": False,
        "audit": {"level": "high", "source": "auto", "ignore": [], "osv-url": "https://api.osv.dev"},
        "concurrency": 16,
        "retries": 3,
        "timeout": 60,
        "overrides": {},
    },
    "gate": {"require-lockfile": True, "sign": False, "scan": True, "audit": True, "licenses": True, "lock-verify": True},
}


class ConfigError(ValueError):
    pass


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict) and k not in ("scopes", "overrides"):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def find_config(start):
    cur = os.path.abspath(start)
    while True:
        for n in NAMES:
            p = os.path.join(cur, n)
            if os.path.isfile(p):
                return p
        if os.path.exists(os.path.join(cur, ".git")):
            return None
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def load(path=None, start="."):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["_path"] = None
    p = path or find_config(start)
    if p:
        try:
            data = yamlite.load_file(p)
        except (OSError, ValueError) as ex:
            raise ConfigError("%s: %s" % (p, ex))
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ConfigError("%s: top-level must be a mapping" % p)
        for k in data:
            if k not in DEFAULTS:
                raise ConfigError("%s: unknown top-level key %r (expected %s)" % (p, k, ", ".join(DEFAULTS)))
        _merge(cfg, data)
        cfg["_path"] = os.path.abspath(p)
    reg = os.environ.get("PK_REGISTRY") or os.environ.get("NPM_CONFIG_REGISTRY")
    if reg:
        cfg["pkg"]["registry"] = reg
    return cfg


def dumps_default():
    return json.dumps({k: v for k, v in DEFAULTS.items()}, indent=2)
