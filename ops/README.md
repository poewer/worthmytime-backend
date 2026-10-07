# Operacje: kopie zapasowe i monitoring

## Kopia zapasowa bazy

`ops/backup.sh` robi dump PostgreSQL (format custom), sprawdza, że plik da się odczytać (`pg_restore --list`), i usuwa kopie starsze niż `RETENTION_DAYS` (domyślnie 14; ostatnia kopia nigdy nie jest usuwana).

```bash
DATABASE_URL=postgresql://wmt:haslo@localhost:5432/worthmytime BACKUP_DIR=/var/backups/wmt ./ops/backup.sh
```

Codziennie o 3:15 (cron):

```
15 3 * * * DATABASE_URL=postgresql://... BACKUP_DIR=/var/backups/wmt /opt/wmt/ops/backup.sh >> /var/log/wmt-backup.log 2>&1
```

Wymagane są narzędzia klienckie PostgreSQL (`postgresql-client`, wersja nie starsza niż serwera). Kopie warto synchronizować poza serwer (np. `rclone`/`rsync` do zewnętrznego magazynu), bo kopia na tym samym dysku nie chroni przed jego awarią.

## Test odtworzenia

`ops/restore-check.sh` wczytuje najnowszą kopię do tymczasowej bazy `wmt_restore_check_<pid>`, sprawdza liczbę tabel, tabelę `alembic_version` i liczbę użytkowników, po czym usuwa bazę. Nie dotyka bazy produkcyjnej (użytkownik musi mieć prawo tworzenia baz).

```bash
DATABASE_URL=postgresql://... BACKUP_DIR=/var/backups/wmt ./ops/restore-check.sh
```

Workflow `Backup check` uruchamia oba skrypty w CI na PostgreSQL 16 (przy zmianach w `ops/` i `migrations/` oraz co poniedziałek), więc regresja w skryptach lub migracjach wyjdzie od razu. Zalecane: raz w miesiącu uruchomić `restore-check.sh` także na prawdziwej kopii produkcyjnej.

## Monitoring dostępności

Workflow `Uptime` co 10 minut odpytuje `GET /api/v1/health` (3 próby, 15 s limitu, oczekuje `200` i `"status": "ok"`, czyli także działającej bazy). Przy awarii przebieg kończy się błędem i GitHub wysyła powiadomienie.

Konfiguracja: w repozytorium *Settings > Secrets and variables > Actions > Variables* dodaj `HEALTH_URL` (np. `https://api.twoja-domena.pl/api/v1/health`). Bez zmiennej workflow tylko się pomija.

`/health` jest wyłączony z limitów żądań, więc częste odpytywanie nie powoduje blokady.
