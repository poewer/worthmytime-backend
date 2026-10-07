#!/usr/bin/env bash
# Test odtworzenia: wczytuje kopię do tymczasowej bazy i sprawdza, że schemat i dane są na miejscu.
# Nie dotyka bazy produkcyjnej: tworzy i usuwa bazę o nazwie wmt_restore_check_<pid>.
#
# Zmienne:
#   DATABASE_URL   adres serwera (postgresql://user:haslo@host:5432/baza), użytkownik musi móc tworzyć bazy
#   BACKUP_FILE    plik kopii (domyślnie najnowszy z BACKUP_DIR)
#   BACKUP_DIR     katalog z kopiami (domyślnie ./backups)
set -euo pipefail

: "${DATABASE_URL:?ustaw DATABASE_URL (postgresql://...)}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
URL="${DATABASE_URL/+asyncpg/}"
BACKUP_FILE="${BACKUP_FILE:-$(find "$BACKUP_DIR" -name 'worthmytime-*.dump' | sort | tail -n 1)}"
[ -n "$BACKUP_FILE" ] && [ -f "$BACKUP_FILE" ] || { echo "[restore] brak pliku kopii" >&2; exit 1; }

# adres serwera bez nazwy bazy + adres bazy testowej
BASE="${URL%/*}"
CHECK_DB="wmt_restore_check_$$"
CHECK_URL="$BASE/$CHECK_DB"

cleanup() { psql "$URL" -qc "DROP DATABASE IF EXISTS $CHECK_DB" > /dev/null 2>&1 || true; }
trap cleanup EXIT

echo "[restore] kopia: $BACKUP_FILE"
psql "$URL" -qc "CREATE DATABASE $CHECK_DB"
pg_restore --no-owner --dbname="$CHECK_URL" "$BACKUP_FILE"

TABLES="$(psql "$CHECK_URL" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
USERS="$(psql "$CHECK_URL" -Atc "SELECT count(*) FROM users")"
VERSION="$(psql "$CHECK_URL" -Atc "SELECT version_num FROM alembic_version" 2>/dev/null || echo brak)"

echo "[restore] tabele: $TABLES, użytkownicy: $USERS, wersja migracji: $VERSION"
[ "$TABLES" -ge 8 ] || { echo "[restore] BŁĄD: za mało tabel po odtworzeniu" >&2; exit 1; }
[ "$VERSION" != "brak" ] || { echo "[restore] BŁĄD: brak tabeli alembic_version" >&2; exit 1; }
echo "[restore] OK: kopia da się odtworzyć"
