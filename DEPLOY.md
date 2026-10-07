# Deploying Phantom on Render

One-time setup, about 15 minutes. Cost: Render's paid plans for the database and the backend (see render.com/pricing).

1. Create an account at render.com and connect your GitHub account.
2. **New > Blueprint**, choose `I-comply/phantom-runtime`, branch `main`. Render reads `render.yaml` and proposes three things: `phantom-db` (Postgres), `phantom-backend`, `phantom-frontend`.
3. It asks for the values marked `sync: false`. Leave `CORS_ORIGINS`, `PHANTOM_PLATFORM_TENANT_ID` and `VITE_BACKEND_URL` empty for now and click **Apply**.
4. When the backend is live, copy its address (`https://phantom-backend-xxxx.onrender.com`) and the frontend's address.
5. Backend > Environment: set `CORS_ORIGINS` to the frontend's address (no trailing slash). Frontend > Environment: set `VITE_BACKEND_URL` to the backend's address, then **Manual Deploy > Clear build cache & deploy**.
6. Check `https://<backend>/api/health` returns OK.

## First admin key
Backend > Environment shows `PHANTOM_BOOTSTRAP_ADMIN_KEY` (generated). Use it once to create your first workspace and admin key:

```bash
BACKEND=https://phantom-backend-xxxx.onrender.com
BOOT=<the generated key>
WS=$(curl -s -X POST $BACKEND/api/workspaces/ -H "X-Bootstrap-Key: $BOOT" -H 'Content-Type: application/json' -d '{"name":"main"}')
echo $WS    # note the "id"
curl -s -X POST $BACKEND/api/v3/security/api-keys -H "X-Bootstrap-Key: $BOOT" -H 'Content-Type: application/json' \
  -d '{"tenant_id":"<id from above>","role":"admin","name":"first-admin"}'
```
The response contains the admin API key once. Save it in a password manager; paste it into the API key field in the web app.

Then **delete `PHANTOM_BOOTSTRAP_ADMIN_KEY`** from the backend's environment, so nobody can create workspaces with it.

## Optional: platform admin
To let one workspace's admin keys see across workspaces, set `PHANTOM_PLATFORM_TENANT_ID` to that workspace's id and redeploy. Leave it empty otherwise.

## After the first deploy of this version
The database is new, so there are no snapshots to rebuild. If you ever restore old data, run `python -m app.scripts.rebuild_snapshots` twice (the second run should print `snapshots rebuilt: 0`).
