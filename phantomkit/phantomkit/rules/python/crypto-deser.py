import hashlib, pickle, yaml, jwt, ssl, tempfile, os, random, requests, tarfile

# ruleid: phantom.python.unsafe-deserialization
data = pickle.loads(blob)
# ruleid: phantom.python.unsafe-deserialization
obj = pickle.load(fh)
# ok: phantom.python.unsafe-deserialization
obj = json.loads(blob)

# ruleid: phantom.python.yaml-unsafe-load
cfg = yaml.load(text)
# ok: phantom.python.yaml-unsafe-load
# ruleid: phantom.python.yaml-unsafe-loader
cfg = yaml.load(text, Loader=yaml.Loader)
# ok: phantom.python.yaml-unsafe-load, phantom.python.yaml-unsafe-loader
cfg = yaml.safe_load(text)
# ok: phantom.python.yaml-unsafe-load, phantom.python.yaml-unsafe-loader
cfg = yaml.load(text, Loader=yaml.SafeLoader)

# ruleid: phantom.python.weak-hash
h = hashlib.md5(b"x").hexdigest()
# ruleid: phantom.python.weak-hash
h = hashlib.sha1(b"x")
# ok: phantom.python.weak-hash
h = hashlib.sha256(b"x")
# ok: phantom.python.weak-hash
h = hashlib.md5(b"x", usedforsecurity=False)

# ruleid: phantom.python.weak-cipher
c = DES.new(key, DES.MODE_CBC, iv)
# ruleid: phantom.python.weak-cipher
c = AES.new(key, AES.MODE_ECB)
# ok: phantom.python.weak-cipher
c = AES.new(key, AES.MODE_GCM, nonce)


def make_reset_token():
    # ruleid: phantom.python.insecure-random-for-secret
    return random.randint(0, 999999)


def pick_color():
    # ok: phantom.python.insecure-random-for-secret
    return random.choice(["red", "blue"])


# ruleid: phantom.python.tls-verification-disabled
requests.get("https://x", verify=False)
# ok: phantom.python.tls-verification-disabled
requests.get("https://x", timeout=3)
# ruleid: phantom.python.tls-verification-disabled
ctx = ssl._create_unverified_context()

# ruleid: phantom.python.jwt-signature-not-verified
jwt.decode(tok, options={"verify_signature": False})
# ok: phantom.python.jwt-signature-not-verified
jwt.decode(tok, key, algorithms=["HS256"])

# ruleid: phantom.python.tempfile-mktemp
p = tempfile.mktemp()

# ruleid: phantom.python.tarfile-extractall
tar.extractall("/tmp/out")
# ok: phantom.python.tarfile-extractall
tar.extractall("/tmp/out", filter="data")
# ok: phantom.python.tarfile-extractall
other.extractall("/tmp/out")

# ruleid: phantom.python.insecure-file-permissions
os.chmod(path, 0o777)
# ok: phantom.python.insecure-file-permissions
os.chmod(path, 0o600)
