# Rollback

The site is static files plus a stateless process; state is only the inquiry and metrics files.

1. **Keep the previous release.** Deploy each build to `releases/<timestamp>/` and point a `current` symlink (or platform release) at it. `dist/MANIFEST.sha256.json` records the SHA-256 of every file in the release.
2. **Roll back:** repoint `current` to the previous release directory and restart the process (`systemctl restart pwx`, or redeploy the previous image tag). No data migration is involved.
3. **Unpublish an asset immediately:** set `publication.approved: false`, `npm run register`, rebuild, redeploy (or, in an emergency, delete that asset's `assets/<slug>/`, `demos/<slug>/`, `decks/<slug>-*` from `dist/` and `assets.json` entry, then restart).
4. **Inquiry data** is never touched by a release; do not delete `/var/lib/pwx` during rollback.
5. **Verify** with `BASE=https://your-domain bash scripts/smoke.sh` and compare a few file hashes with the manifest of the release you rolled back to.

Rollback was exercised locally only in the sense that every build is a clean `dist/` regeneration; no hosted environment exists.
