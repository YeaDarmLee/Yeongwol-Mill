#!/bin/bash
# MySQL Database Backup Script with S3 Upload for 영월고향방앗간
set -e

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/var/backups/yeongwol_db"
DB_NAME=${MYSQL_DB:-"yeongwol_mill"}
DB_USER=${MYSQL_USER:-"root"}
DB_PASS=${MYSQL_PASSWORD:-""}
S3_BUCKET=${S3_BACKUP_BUCKET:-"s3://yeongwol-mill-backups"}

mkdir -p $BACKUP_DIR
BACKUP_FILE="$BACKUP_DIR/db_${DB_NAME}_${DATE}.sql.gz"

echo "[$(date)] Starting MySQL backup..."
mysqldump -u $DB_USER ${DB_PASS:+-p$DB_PASS} --single-transaction --routines --triggers $DB_NAME | gzip > $BACKUP_FILE

echo "[$(date)] Backup created: $BACKUP_FILE"

# Upload to S3 / Object Storage (if AWS CLI is configured)
if command -v aws &> /dev/null; then
    echo "[$(date)] Uploading backup to $S3_BUCKET..."
    aws s3 cp $BACKUP_FILE "$S3_BUCKET/$(basename $BACKUP_FILE)"
    echo "[$(date)] S3 upload completed."
fi

# Retain 30 days of local backups
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete
echo "[$(date)] Backup process completed successfully!"
