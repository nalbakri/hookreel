# Upgrading HookReel

## Before you upgrade

Always back up your config and database first:

    cp config/.env config/.env.backup
    cp -r data/ data.backup/

## Standard upgrade

    docker compose pull
    docker compose up -d

HookReel runs database migrations automatically on startup.
No manual schema changes are needed between patch versions.

## Version-specific notes

### v1.0 Hook -- Initial release

No upgrade path -- this is the first release.

### Future versions

Migration notes will be added here for each release.
Check CHANGELOG.md for what changed before upgrading.

## Rollback

If something goes wrong after upgrading:

    docker compose down
    docker tag nalbakri/hookreel:previous nalbakri/hookreel:latest
    docker compose up -d
    cp config/.env.backup config/.env

## Checking your current version

    docker exec hookreel python -c "import app.config as c; print(c.VERSION, c.VERSION_NAME)"
