Implement the internal Acme release packaging and verification CLI (`scripts/build_release.py`), resolve any database migration reversibility issues under `migrations/`, and generate the verified `1.4.0` release bundle at `releases/release-1.4.0/`.

Requirements summary:
1. Read `README.md` and explore Acme's release engineering documentation under `docs/` (`docs/README.md` and linked documents) before making changes. Follow active canonical standards rather than deprecated legacy docs.
2. Ensure every migration pair under `migrations/` satisfies Acme's reversibility mandate.
3. Implement `scripts/build_release.py` (accepting `--out`, defaulting to `releases/release-1.4.0`) strictly obeying Acme's active pre-flight verification workflow, release bundle layout, metadata schema, and integrity sealing rules.
4. Add automated tests under `tests/`, run `pytest`, and generate the clean `releases/release-1.4.0/` bundle.
