"""U1.1 signed update metadata, local keys and explicit per-library trust.

This is a narrowly scoped signed-feed protocol, not a full TUF implementation.
HTTP provides no confidentiality. First-contact publisher authentication must
come from a separately trusted package or an out-of-band key fingerprint.
"""
from copy import deepcopy
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import threading
import uuid
from urllib.parse import urljoin, urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

from core.odrlib import OdrLibError
from core.paths import data_dir
from core.persistence import save_json

PROTOCOL = "U1.1"
DOMAIN = b"ODeR U1.1 signed update feed\x00"
_LOCK = threading.RLock()


def runtime_self_test():
    """Exercise the packaged signing backend without network or persistent keys."""
    key = Ed25519PrivateKey.generate()
    message = DOMAIN + b"packaged runtime check"
    signature = key.sign(message)
    key.public_key().verify(signature, message)


def update_url(value, *, allow_http=False):
    if not isinstance(value, str) or len(value) > 4096 or value != value.strip():
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ({"http", "https"} if allow_http else {"https"})
                or not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.fragment or any(ord(c) < 33 or ord(c) == 127 for c in value)):
            return None
        parsed.port
    except ValueError:
        return None
    return value


def strict_json(data):
    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise OdrLibError("Duplicate fields are not allowed in update metadata.")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _v: (_ for _ in ()).throw(ValueError("Non-finite number")))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise OdrLibError(f"Invalid update JSON: {exc}") from exc


def _canonical(value):
    def check(node):
        if node is None or type(node) in (str, bool):
            return
        if type(node) is int and -(2**53 - 1) <= node <= 2**53 - 1:
            return
        if isinstance(node, list):
            for child in node:
                check(child)
            return
        if isinstance(node, dict) and all(isinstance(key, str) for key in node):
            for child in node.values():
                check(child)
            return
        raise OdrLibError("Signed metadata requires JSON strings, safe integers, booleans, lists and objects.")
    check(value)
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def _decode(value, length):
    try:
        result = base64.b64decode(value, validate=True)
        if len(result) != length:
            raise ValueError("Wrong length")
        return result
    except (ValueError, TypeError) as exc:
        raise OdrLibError("Invalid signing key or signature encoding.") from exc


def validate_key(value):
    if not isinstance(value, dict) or set(value) != {"algorithm", "public_key", "key_id"} or value["algorithm"] != "ed25519":
        raise OdrLibError("U1.1 requires an Ed25519 publisher public key.")
    raw = _decode(value["public_key"], 32)
    if value["key_id"] != hashlib.sha256(raw).hexdigest():
        raise OdrLibError("The publisher key fingerprint does not match its public key.")
    return dict(value)


def _key_path(key_id):
    if not isinstance(key_id, str) or not re.fullmatch(r"[0-9a-f]{64}", key_id):
        raise OdrLibError("Invalid local signing key reference.")
    return os.path.join(data_dir(), "creator", "signing-keys", key_id + ".pem")


def create_signing_key():
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes_raw()
    descriptor = {"algorithm": "ed25519", "public_key": base64.b64encode(raw).decode("ascii"),
                  "key_id": hashlib.sha256(raw).hexdigest()}
    path = _key_path(descriptor["key_id"])
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    descriptor_fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor_fd, "wb") as output:
        output.write(pem)
        output.flush()
        os.fsync(output.fileno())
    return descriptor


def load_signing_key(descriptor):
    descriptor = validate_key(descriptor)
    try:
        with open(_key_path(descriptor["key_id"]), "rb") as source:
            key = serialization.load_pem_private_key(source.read(8192), password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise OdrLibError("The local signing key is missing or unreadable. Restore it on this Creator computer; do not generate a replacement for an existing publisher.") from exc
    if not isinstance(key, Ed25519PrivateKey) or key.public_key().public_bytes_raw() != _decode(descriptor["public_key"], 32):
        raise OdrLibError("The local private key does not match this library's publisher.")
    return key


def signing_key_directory():
    return os.path.dirname(_key_path("0" * 64))


def _time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Missing timezone")
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError) as exc:
        raise OdrLibError("Signed update metadata needs valid UTC expiry timestamps.") from exc


def sign_feed(feed, descriptor, *, validity_days=30, now=None):
    if type(validity_days) is not int or not 1 <= validity_days <= 365:
        raise OdrLibError("Feed validity must be between 1 and 365 days.")
    signed = deepcopy(feed)
    signed["format_version"] = "1.1"
    signed["signing_key"] = validate_key(descriptor)
    now = now or datetime.now(timezone.utc)
    signed["issued_at"] = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    signed["expires_at"] = (now + timedelta(days=validity_days)).isoformat(timespec="seconds").replace("+00:00", "Z")
    signature = load_signing_key(descriptor).sign(DOMAIN + _canonical(signed))
    return {"format": feed["format"], "format_version": "1.1", "signed": signed,
            "signature": base64.b64encode(signature).decode("ascii")}


def verify_feed(envelope, *, trusted_key=None, now=None):
    if not isinstance(envelope, dict) or set(envelope) != {"format", "format_version", "signed", "signature"}:
        raise OdrLibError("The signed update envelope is malformed.")
    signed = envelope["signed"]
    if envelope["format_version"] != "1.1" or not isinstance(signed, dict) or signed.get("format") != envelope["format"] or signed.get("format_version") != "1.1":
        raise OdrLibError("The signed update format does not match its envelope.")
    key = validate_key(signed.get("signing_key"))
    if trusted_key is not None and key != validate_key(trusted_key):
        raise OdrLibError("The publisher key changed. This update cannot replace a trusted library.")
    try:
        Ed25519PublicKey.from_public_bytes(_decode(key["public_key"], 32)).verify(
            _decode(envelope["signature"], 64), DOMAIN + _canonical(signed))
    except InvalidSignature as exc:
        raise OdrLibError("The update feed's publisher signature is invalid.") from exc
    now = now or datetime.now(timezone.utc)
    issued, expires = _time(signed.get("issued_at")), _time(signed.get("expires_at"))
    if issued > now + timedelta(minutes=5) or expires <= now or not timedelta(0) < expires - issued <= timedelta(days=365):
        raise OdrLibError("The signed update feed has expired or its timestamps are invalid. Ask the publisher for a refreshed feed; check your computer's clock.")
    return deepcopy(signed)


def _trust_path(library_id):
    try:
        identifier = str(uuid.UUID(str(library_id)))
    except ValueError as exc:
        raise OdrLibError("Invalid library trust identity.") from exc
    return os.path.join(data_dir(), "library-update-trust", identifier + ".json")


def trusted_state(library_id):
    path = _trust_path(library_id)
    with _LOCK:
        # Never recover an older backup: that would roll back the high-water mark.
        try:
            with open(path, "rb") as source:
                value = strict_json(source.read(16384))
        except FileNotFoundError:
            return None
        except (OSError, OdrLibError) as exc:
            raise OdrLibError("Library update trust data is unreadable; refusing to reset publisher trust.") from exc
        if value is None:
            raise OdrLibError("Invalid stored publisher trust.")
        if value is not None:
            if not isinstance(value, dict) or value.get("library_id") != library_id:
                raise OdrLibError("Invalid stored publisher trust.")
            validate_key(value.get("key"))
            if type(value.get("revision")) is not int or value["revision"] < 1:
                raise OdrLibError("Invalid stored update revision.")
            if value.get("package_sha256") is not None and not re.fullmatch(r"[0-9a-f]{64}", str(value["package_sha256"])):
                raise OdrLibError("Invalid stored package digest.")
            if value.get("issued_at") is not None:
                _time(value["issued_at"])
        return value


def pin_key(library_id, key, fingerprint, revision, *, package_sha256=None):
    key = validate_key(key)
    if fingerprint.replace(" ", "").casefold() != key["key_id"]:
        raise OdrLibError("The confirmed fingerprint does not match the publisher key.")
    with _LOCK:
        current = trusted_state(library_id)
        if current:
            if current["key"] != key:
                raise OdrLibError("A different publisher key is already trusted for this library.")
            return current
        value = {"library_id": library_id, "key": key, "revision": revision, "package_sha256": package_sha256,
                 "issued_at": None}
        save_json(_trust_path(library_id), value, backup=False)
        return value


def record_verified_feed(feed):
    with _LOCK:
        state = trusted_state(feed.library_id)
        if not state or state["key"] != feed.signing_key:
            raise OdrLibError("Trust this library's publisher key before checking updates.")
        issued = feed.signed_envelope["signed"]["issued_at"]
        if feed.revision < state["revision"]:
            raise OdrLibError("The update feed attempted to roll back a previously seen revision.")
        if state.get("issued_at") and _time(issued) < _time(state["issued_at"]):
            raise OdrLibError("An older signed feed was replayed.")
        if feed.revision == state["revision"] and state.get("package_sha256") not in (None, feed.sha256):
            raise OdrLibError("The publisher changed package bytes without increasing the revision.")
        state.update(revision=feed.revision, package_sha256=feed.sha256, issued_at=issued)
        save_json(_trust_path(feed.library_id), state, backup=False)


def get_response(session, url, *, allow_http=False, **kwargs):
    """Validate every redirect BEFORE following it; never silently downgrade TLS."""
    for _ in range(6):
        if not update_url(url, allow_http=allow_http):
            raise OdrLibError("Unsafe update URL. HTTP requires U1.1 signed updates; credentials and fragments are not allowed.")
        response = session.get(url, allow_redirects=False, **kwargs)
        status = getattr(response, "status_code", 200)
        if status not in (301, 302, 303, 307, 308):
            return response
        location = getattr(response, "headers", {}).get("Location")
        response.close()
        if not location:
            raise OdrLibError("Update redirect has no destination.")
        target = urljoin(url, location)
        if urlsplit(url).scheme == "https" and urlsplit(target).scheme != "https":
            raise OdrLibError("The update server redirected HTTPS to an insecure transport.")
        url = target
    raise OdrLibError("Too many update redirects.")
