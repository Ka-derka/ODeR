# U1.1 signed library updates — testing build

U1.1 adds publisher-signed update feeds to `.odrlib` v1. It allows HTTP as well
as HTTPS for the feed, package download and T2 update-torrent metadata. Ordinary
catalog source URLs keep their existing rules. Legacy U1 HTTPS libraries still work.

This is step 2 of the update/hosting work. It does not implement ODeR Hoster,
automatic key rotation, a public publisher directory or unattended publishing.
Application versions remain ODeR 1.1.0-beta.1 and Creator 2026.0.2a for these test
installers; this is not a new GitHub release or an automatic application update.

## Creator: publishing and refreshing

1. Open the library's **Online updates** section.
2. Select **U1.1 · Signed HTTP / HTTPS updates** and **Create signing identity**.
3. Enter the feed and package URLs. For a local test, use, for example,
   `http://127.0.0.1:8000/library.odrlib-feed.json` and
   `http://127.0.0.1:8000/library.odrlib`.
4. Set feed validity (default 30 days; 1–365 days supported).
5. Optionally enable T2 and enter the URL of `library.odrlib.torrent`.
6. Save the project and create `library.odrlib` in a dedicated publishing folder.
7. Upload the package and optional package torrent, seed the package if using
   T2, then publish the generated feed **last**. Do not hand-edit the feed:
   changing signed fields invalidates its signature.
8. Share the publisher fingerprint through a separate trusted channel.

For another release, use **Library → Prepare next revision**, edit the library,
and rebuild. Every change to package bytes requires a higher revision, even if
the visible version text stays the same. Do not rebuild an already-published
revision to extend expiry.

Instead, use **Library → Refresh signed feed…** and select the exact published
package. This checks the package and signs a new expiry without changing its
bytes or revision. A T2 refresh also regenerates the package torrent sidecar;
upload that sidecar before replacing the refreshed feed. Refresh runs in a
background worker, including when checking large packages.

The project contains only the public signing identity. The unencrypted private
PEM key lives in `creator/signing-keys` under ODeR's per-user application-data
folder. Creator shows the exact folder when creating a key. On Windows this is
normally `%LOCALAPPDATA%/ODeR/creator/signing-keys`; macOS uses Application Support.
Keep a secure private backup. Moving just the `.odrproj` to another computer is
not enough to sign updates; restore the matching PEM to its key folder there.
Never serve that folder, copy it into a package, or commit it to Git.

## ODeR: trusting and updating

Importing a package neither contacts its update server nor trusts its publisher.
The library information/import summary displays its public fingerprint.

On the first **Check for updates**, compare the fingerprint against a trusted
source and explicitly approve the publisher. Trust is stored per library ID,
separately from profiles, so importing another copy cannot reset it. Later
updates must use that same key. Canceling the prompt makes no network request.

An update is offered only after signature, expiry, library identity, channel,
revision and URL validation. The complete package size and SHA-256 are checked
before import. T2 metainfo is bound into the same signature; package delivery
from peers has the same final checks and can fall back to the configured server.

## Security boundaries

- HTTP is **not encrypted**. Signatures protect integrity, not request privacy,
  availability or the identity of a key obtained from an untrusted first package.
- First-contact trust is a user decision, not a verified publisher badge. An
  attacker who replaces both an initial package and its fingerprint can impersonate
  a publisher unless the recipient checks a separate trusted source.
- A trusted publisher can publish harmful files. Updates do not run them automatically.
- Missing/invalid signatures, changed keys, unsigned downgrade attempts, wrong
  channels, expired feeds and future-dated feeds are rejected.
- Previously seen revision, package digest and issue time persist even when an
  offered download is canceled. Older revisions/timestamps and changed bytes at
  the same revision are rejected. Corrupt trust state fails closed rather than
  restoring an older backup. Local deletion/tampering of application data is not
  defended against.
- Every redirect is validated before following it. URL credentials/fragments and
  HTTPS-to-HTTP redirects are rejected, including for signed feeds.
- The computer's clock must be reasonably correct. Expiry limits replay duration
  but cannot guarantee that a server has supplied the newest available feed.
- Key rotation/recovery is deliberately not automatic. Losing a key means
  restoring its private backup or creating a separate library identity with a
  new explicit trust decision. There is no “ignore signature error” option.
- This is a scoped Ed25519 signed-feed protocol, not a full TUF implementation
  or an independently audited security system.

## Wire format for custom builders

The `.odrlib` core format stays at version 1. Its manifest must declare
`{"id":"U","version":"1.1"}` in `extensions.required` (the version is a JSON
string, **not** floating-point 1.1). Older readers must reject it. `library.json`
uses `update.protocol = "U1.1"` and `update.signing_key`:

```json
{"algorithm":"ed25519","public_key":"BASE64_RAW_32_BYTES","key_id":"SHA256_HEX_OF_RAW_PUBLIC_KEY"}
```

The feed envelope has exactly `format`, `format_version`, `signed`, `signature`.
Its format ID is the existing ODeR library-feed ID and version is the string
`"1.1"`. The `signed` object contains the legacy feed fields (`library_id`,
`channel`, `latest`, etc.), version `"1.1"`, `signing_key`, `issued_at` and
`expires_at`. `latest.torrent`, if present, is covered by the signature.

Ed25519 signs `b"ODeR U1.1 signed update feed\x00"` followed by the ASCII bytes
of Python-compatible canonical JSON: `json.dumps(signed, ensure_ascii=True,
sort_keys=True, separators=(",", ":"), allow_nan=False)`. Duplicate keys are
rejected. Floats and integers outside ±(2^53−1) are not allowed. The signature
is standard base64 of 64 raw bytes. See `core/update_security.py` for the
reference codec and `tests/test_u11_updates.py` for integration examples.

## Quick testing checklist

- [ ] Build and import a simple U1.1 library; fingerprint is visible.
- [ ] Cancel the trust prompt: no request reaches the HTTP server.
- [ ] Trust the fingerprint; an unchanged library reports current.
- [ ] Publish revision 2 over localhost HTTP and update revision 1 in ODeR.
- [ ] Change one signed feed field: ODeR rejects it, keeping the installed library.
- [ ] Replace the package at its URL with different bytes: download is rejected.
- [ ] Offer revision 3, cancel, then serve revision 2: rollback is rejected.
- [ ] Refresh the exact published package: its checksum stays unchanged.
- [ ] Test U1.1 + T2 with peers, then without peers to exercise server fallback.
- [ ] Check an existing U1 HTTPS library still updates normally.

Serve only a dedicated publishing folder for localhost testing, never your
home directory, project directory, downloads or application-data/key folder.
For example, with Python installed: `python -m http.server 8000 --bind 127.0.0.1
--directory "C:/path/to/publish-only"` (one command). Do not expose that test
server to the internet. Hoster will be a separate follow-up.

The Windows test suite includes a real loopback HTTP update, tamper/replay/key
tests, Qt UI checks and T2 metadata checks. macOS execution still needs CI/a Mac.
Intel builds pin cryptography 48.0.1 because upstream removed Intel macOS wheel
support in 49.0.0; see the [upstream changelog](https://cryptography.io/en/latest/changelog/#v49-0-0).
Revisit that compatibility pin before a public release. ODeR uses Ed25519, not
the PKCS7 decryption functionality changed in cryptography 50.
