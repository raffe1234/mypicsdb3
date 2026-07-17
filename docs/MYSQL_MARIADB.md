# MySQL and MariaDB

SQLite is the default and needs no setup. Use MySQL/MariaDB only when all Kodi
clients can access the same source URIs, for example the same `smb://` paths.

## Create the database manually

Run as a database administrator and choose a strong password:

```sql
CREATE DATABASE mypicsdb3
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_bin;

CREATE USER 'mypicsdb3'@'%' IDENTIFIED BY 'replace-this-password';
GRANT ALL PRIVILEGES ON mypicsdb3.* TO 'mypicsdb3'@'%';
FLUSH PRIVILEGES;
```

Then set:

- Database backend: MySQL or MariaDB
- Host and port
- Database name: `mypicsdb3`
- Username and password

Use **Scan status > Test database connection** before scanning.

## Shared scanner behaviour

The database contains an expiring catalogue scan lock. Only one Kodi client can
scan at a time. Other clients may continue reading widgets while a scan runs.
Choose one device as the regular background scanner and disable automatic scans
on the others.

## Path consistency

The catalogue stores original Kodi URIs, not device-local translated paths or
texture-cache paths. Every client must therefore resolve the same URI. Kodi
creates its own local thumbnail cache lazily on each device.

## Backup

For MariaDB:

```bash
mariadb-dump -u mypicsdb3 -p --single-transaction mypicsdb3 > mypicsdb3.sql
```
