# Security Incident: tracked `project.zip`

`project.zip` was committed in `fc8bcea` and contained `.env`, an authorized
Telethon session and a CRM database. Deleting the archive from the latest tree
does not remove it from Git history.

## Mandatory response before production

1. Revoke and regenerate `BOT_TOKEN` in BotFather.
2. Revoke the exposed LLM API key.
3. Terminate all Telegram devices/sessions for the service account.
4. Create a new Telethon session using a dedicated service account.
5. Set a new `PII_ENCRYPTION_KEY` and a separate `BACKUP_ENCRYPTION_KEY`.
6. Set `SECRETS_ROTATED_AT` to the actual ISO-8601 completion time.

## Rewrite Git history

Coordinate this operation with every repository user. All old clones must be
discarded after the force-push.

```bash
pip install git-filter-repo
git filter-repo --path project.zip \
  --path chat_monitor_bot_settings_changes.zip \
  --path chat_monitor_changes.zip \
  --path qa_fixes_changes.zip \
  --invert-paths
git push --force --all
git push --force --tags
```

Also delete affected releases, CI artifacts, caches and forks where possible.
History rewriting cannot revoke secrets already copied by third parties; token
and session rotation is mandatory.

## Verify

```bash
python -m scripts.check_tracked_secrets
python -m scripts.production_readiness
```
