#!/usr/bin/env bash
# Kopia zapasowa bazy PostgreSQL: dump w formacie custom, kontrola czytelności i retencja.
#
# Zmienne:
#   DATABASE_URL      adres bazy w postaci postgresql://user:haslo@host:5432/baza (bez "+asyncpg")
#   BACKUP_DIR        katalog na kopie (domyślnie ./backups)
#   RETENTION_DAYS    ile dni trzymać kopie (domyślnie 14)
#
# Przykład (cron, codziennie o 3:15):  15 3 * * * DATABASE_URL=... /opt/wmt/ops/backup.sh
set -euo pipefail

: "${DATABASE_URL:?ustaw DATABASE_URL (postgresql://...)}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

# sqlalchemy używa "postgresql+asyncpg://", narzędzia pg_* rozumieją tylko "postgresql://"
URL="${DATABASE_URL/+asyncpg/}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$BACKUP_DIR/worthmytime-$STAMP.dump"

echo "[backup] zapis do $FILE"
pg_dump --format=custom --no-owner --file="$FILE.part" "$URL"

# kopia musi dać się odczytać, zanim uznamy ją za gotową (częściowy plik nie trafia do retencji)
pg_restore --list "$FILE.part" > /dev/null
mv "$FILE.part" "$FILE"
echo "[backup] gotowe: $(du -h "$FILE" | cut -f1)"

# retencja: usuń kopie starsze niż RETENTION_DAYS (nigdy nie usuwaj ostatniej kopii)
COUNT="$(find "$BACKUP_DIR" -name 'worthmytime-*.dump' | wc -l)"
if [ "$COUNT" -gt 1 ]; then
  find "$BACKUP_DIR" -name 'worthmytime-*.dump' -mtime +"$RETENTION_DAYS" -print -delete | sed 's/^/[backup] usunięto stare: /'
fi
echo "[backup] kopii w katalogu: $(find "$BACKUP_DIR" -name 'worthmytime-*.dump' | wc -l)"
