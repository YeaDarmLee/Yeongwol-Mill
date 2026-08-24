#!/bin/bash
# Isolated DB Backup Restore Test Script for 영월고향방앗간
set -e

BACKUP_DIR="/var/backups/yeongwol_db"
LATEST_BACKUP=$(ls -t $BACKUP_DIR/*.sql.gz 2>/dev/null | head -n 1)

if [ -z "$LATEST_BACKUP" ]; then
    echo "Error: No backup files found in $BACKUP_DIR"
    exit 1
fi

TEST_DB="yeongwol_restore_test_db"
DB_USER=${MYSQL_USER:-"root"}
DB_PASS=${MYSQL_PASSWORD:-""}

echo "[$(date)] Starting restore test using latest backup: $LATEST_BACKUP"
echo "Creating isolated test database: $TEST_DB..."

mysql -u $DB_USER ${DB_PASS:+-p$DB_PASS} -e "DROP DATABASE IF EXISTS $TEST_DB; CREATE DATABASE $TEST_DB DEFAULT CHARACTER SET utf8mb4;"

echo "Restoring data into $TEST_DB..."
gunzip -c $LATEST_BACKUP | mysql -u $DB_USER ${DB_PASS:+-p$DB_PASS} $TEST_DB

# Verification Check
ORDER_COUNT=$(mysql -u $DB_USER ${DB_PASS:+-p$DB_PASS} -N -e "SELECT COUNT(*) FROM orders;" $TEST_DB)
PRODUCT_COUNT=$(mysql -u $DB_USER ${DB_PASS:+-p$DB_PASS} -N -e "SELECT COUNT(*) FROM products;" $TEST_DB)

echo "[$(date)] Verification Result:"
echo "  - Products in restored DB: $PRODUCT_COUNT"
echo "  - Orders in restored DB: $ORDER_COUNT"

mysql -u $DB_USER ${DB_PASS:+-p$DB_PASS} -e "DROP DATABASE $TEST_DB;"
echo "[$(date)] Restore test PASSED successfully! Test DB cleaned up."
