"""Master key providers. A provider returns versioned master keys; derived keys (ledger MAC, anchors,
principal secrets) are computed from the master of a given version, so old data keeps verifying after rotation.
Non-file providers never write plaintext key material to disk and never log it."""
import base64, json, os, secrets, urllib.request
from pathlib import Path
from .util import http_open


class KeyError_(Exception):
    pass


def _key(hexs):
    try:
        k = bytes.fromhex(hexs.strip())
    except (ValueError, AttributeError):
        raise KeyError_("master key is not valid hex")
    if len(k) < 16:
        raise KeyError_("master key too short")
    return k


class KeyProvider:
    name = "base"

    def current_version(self):
        raise NotImplementedError

    def get(self, version):
        raise NotImplementedError

    def rotate(self):
        raise KeyError_(f"provider {self.name} does not support rotation")

    def current(self):
        return self.get(self.current_version())


class FileProvider(KeyProvider):
    """master.key = version 1 (unchanged layout); master.key.vN = later versions."""
    name = "file"

    def __init__(self, d):
        self.dir = Path(d)
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self._path(1).exists():
            self._write(1)

    def _path(self, v):
        return self.dir / ("master.key" if v == 1 else f"master.key.v{v}")

    def _write(self, v):
        fd = os.open(self._path(v), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))

    def current_version(self):
        v = 1
        while self._path(v + 1).exists():
            v += 1
        return v

    def get(self, version):
        p = self._path(version)
        if not p.exists():
            raise KeyError_(f"unknown master key version {version}")
        return _key(p.read_text())

    def rotate(self):
        v = self.current_version() + 1
        self._write(v)
        return v


class EnvProvider(KeyProvider):
    """ATL_MASTER_KEY_HEX = current (ATL_MASTER_KEY_VERSION, default 1); ATL_MASTER_KEY_HEX_V<n> = older versions."""
    name = "env"

    def __init__(self, environ=None):
        self.env = os.environ if environ is None else environ
        if not self.env.get("ATL_MASTER_KEY_HEX"):
            raise KeyError_("ATL_MASTER_KEY_HEX not set")
        self.ver = int(self.env.get("ATL_MASTER_KEY_VERSION", "1"))

    def current_version(self):
        return self.ver

    def get(self, version):
        if version == self.ver:
            return _key(self.env["ATL_MASTER_KEY_HEX"])
        h = self.env.get(f"ATL_MASTER_KEY_HEX_V{version}")
        if not h:
            raise KeyError_(f"unknown master key version {version}")
        return _key(h)


class EnvelopeProvider(KeyProvider):
    """Master held in memory only. Disk holds only wrapped (encrypted) data keys: {version: ciphertext_b64}."""

    def __init__(self, d):
        self.file = Path(d) / f"master.{self.name}.json"
        self._mem = {}
        if not self.file.exists():
            self._add(1)

    def _load(self):
        return {int(k): v for k, v in json.loads(self.file.read_text()).items()}

    def _add(self, v):
        wraps = self._load() if self.file.exists() else {}
        plain, ct = self.generate()
        wraps[v] = base64.b64encode(ct).decode()
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(wraps, sort_keys=True))
        os.replace(tmp, self.file)
        self._mem[v] = plain

    def current_version(self):
        return max(self._load())

    def get(self, version):
        if version not in self._mem:
            ct = self._load().get(version)
            if ct is None:
                raise KeyError_(f"unknown master key version {version}")
            self._mem[version] = self.decrypt(base64.b64decode(ct))
        return self._mem[version]

    def rotate(self):
        v = self.current_version() + 1
        self._add(v)
        return v

    def generate(self):  # -> (plaintext 32 bytes, ciphertext bytes)
        raise NotImplementedError

    def decrypt(self, ct):
        raise NotImplementedError


class AwsKmsProvider(EnvelopeProvider):
    name = "aws-kms"

    def __init__(self, d, client=None, key_id=None):
        self.key_id = key_id or os.environ.get("ATL_KMS_KEY_ID")
        if not self.key_id:
            raise KeyError_("ATL_KMS_KEY_ID not set")
        if client is None:
            import boto3  # lazy: optional dependency
            client = boto3.client("kms")
        self.kms = client
        super().__init__(d)

    def generate(self):
        r = self.kms.generate_data_key(KeyId=self.key_id, KeySpec="AES_256")
        return r["Plaintext"], r["CiphertextBlob"]

    def decrypt(self, ct):
        return self.kms.decrypt(CiphertextBlob=ct, KeyId=self.key_id)["Plaintext"]


class _Vault:
    def __init__(self, addr=None, token=None):
        self.addr = (addr or os.environ.get("ATL_VAULT_ADDR", "")).rstrip("/")
        self.token = token or os.environ.get("ATL_VAULT_TOKEN", "")
        if not (self.addr and self.token):
            raise KeyError_("ATL_VAULT_ADDR / ATL_VAULT_TOKEN not set")

    def call(self, method, path, body=None):
        req = urllib.request.Request(f"{self.addr}/v1/{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Vault-Token": self.token, "Content-Type": "application/json"})
        try:
            with http_open(req, 10) as r:
                raw = r.read()
        except Exception as e:
            raise KeyError_(f"vault request failed: {type(e).__name__}")
        return json.loads(raw) if raw else {}


class VaultTransitProvider(EnvelopeProvider):
    """Data key generated and wrapped by Vault transit; only the wrapped key is stored locally."""
    name = "vault-transit"

    def __init__(self, d, addr=None, token=None, key=None, mount=None):
        self.v = _Vault(addr, token)
        self.tkey = key or os.environ.get("ATL_VAULT_KEY", "atl-master")
        self.mount = mount or os.environ.get("ATL_VAULT_MOUNT", "transit")
        super().__init__(d)

    def generate(self):
        r = self.v.call("POST", f"{self.mount}/datakey/plaintext/{self.tkey}", {"bits": 256})["data"]
        return base64.b64decode(r["plaintext"]), r["ciphertext"].encode()

    def decrypt(self, ct):
        r = self.v.call("POST", f"{self.mount}/decrypt/{self.tkey}", {"ciphertext": ct.decode()})["data"]
        return base64.b64decode(r["plaintext"])


class VaultKVProvider(KeyProvider):
    """KV v2 secret {"current": n, "v1": hex, ...}. Nothing is written locally."""
    name = "vault"

    def __init__(self, d=None, addr=None, token=None, path=None, mount=None):
        self.v = _Vault(addr, token)
        self.path = path or os.environ.get("ATL_VAULT_PATH", "atl/master")
        self.mount = mount or os.environ.get("ATL_VAULT_MOUNT", "secret")
        self._cache = None
        try:
            self._data()
        except KeyError_:
            self._put({"current": 1, "v1": secrets.token_hex(32)})

    def _data(self):
        if self._cache is None:
            self._cache = self.v.call("GET", f"{self.mount}/data/{self.path}")["data"]["data"]
        return self._cache

    def _put(self, data):
        self.v.call("POST", f"{self.mount}/data/{self.path}", {"data": data})
        self._cache = data

    def current_version(self):
        return int(self._data()["current"])

    def get(self, version):
        h = self._data().get(f"v{version}")
        if not h:
            raise KeyError_(f"unknown master key version {version}")
        return _key(h)

    def rotate(self):
        data = dict(self._data())
        v = int(data["current"]) + 1
        data[f"v{v}"], data["current"] = secrets.token_hex(32), v
        self._put(data)
        return v


def make_provider(d):
    kind = os.environ.get("ATL_KEY_PROVIDER")
    if kind is None:  # backwards compatible: env var wins, else file
        kind = "env" if os.environ.get("ATL_MASTER_KEY_HEX") else "file"
    if kind == "file":
        return FileProvider(d)
    if kind == "env":
        return EnvProvider()
    if kind == "aws-kms":
        return AwsKmsProvider(d)
    if kind == "vault":
        return VaultTransitProvider(d) if os.environ.get("ATL_VAULT_MODE") == "transit" else VaultKVProvider(d)
    raise KeyError_(f"unknown ATL_KEY_PROVIDER {kind!r}")
