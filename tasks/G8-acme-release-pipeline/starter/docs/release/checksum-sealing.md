# Checksum Sealing & Bundle Hygiene

> **Status:** Active (Canonical — Effective 2026-01-01)

1. After writing `<bundle_dir>/release-manifest.json`, generate `<bundle_dir>/MANIFEST.sha256` with standard GNU two-space format:
   ```text
   <64-hex-sha256>  release-manifest.json
   ```
   (Notice the **two spaces** between `<sha256>` and `release-manifest.json`, ending with `\n`.)

2. Verify the seal inside `<bundle_dir>` as the final pipeline step (`sha256sum -c MANIFEST.sha256` or equivalent exact byte digest check).

3. **Forbidden Bundle Files**:
   NEVER leave `.tmp`, `.bak`, `.pyc`, or `__pycache__` files or directories anywhere inside `<bundle_dir>`.
