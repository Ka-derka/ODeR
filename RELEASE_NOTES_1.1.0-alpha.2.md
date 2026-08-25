# ODeR 1.1.0 Alpha 2

Alpha 2 turns Creator-built `.odrlib` packages into libraries you can actually use in ODeR. Drop a package into the app or double-click it, review its artwork and curator details, then import it as a managed read-only library.

## What is new

- Import and fully validate `.odrlib` version 1 packages before anything is installed.
- Browse folders and files offline with search, details, resizable columns, and source availability.
- Download from ordinary HTTPS mirrors through ODeR's Downloads view.
- Extract bundled offline files with size and SHA-256 verification.
- Check curator-provided update feeds and install only packages that match the library identity, revision, size, and checksum.
- Always show **Check for updates**; packages without a feed now explain what the curator needs to publish instead of hiding the feature.
- Handle duplicate libraries by importing a separate copy or replacing an existing revision.
- Show package artwork, version, curator, category, tags, source, and update date in the import and information views.
- Save an installed `.odrlib` back out as a shareable copy.
- Open `.odrlib` files through drag-and-drop, command-line forwarding, or the Windows file association.
- Use a formal extension declaration inside `.odrlib` v1. Self-updating libraries now identify themselves as `U1`; unsupported required extensions are rejected before import, while safe optional extensions can coexist with older readers.
- Install ODeR and Creator through Windows installers; new releases no longer publish portable executables or ZIPs.
- Build native macOS `.app` bundles and DMGs for both ODeR and ODeR Creator, including document associations and macOS Application Support storage.

## Versioning

ODeR and ODeR Creator now have separate release lines. The browser is **1.1.0-alpha.2**. Creator remains **2026.0.1a** and continues using calendar-style `YYYY.X.Y` naming.

## Safety

ODeR never runs files contained in a library. It rejects unsafe paths, undeclared or duplicate members, unsupported required capabilities or extensions, invalid catalog references, oversized content, hash mismatches, and update packages belonging to a different library. Local downloads and preferences are retained when a curated library is updated.

This is a preview release. Installed testers need the **Preview releases** update channel enabled.
