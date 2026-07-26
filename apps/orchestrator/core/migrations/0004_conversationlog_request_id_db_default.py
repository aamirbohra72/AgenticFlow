# Ensure request_id has a DB-level default so inserts never send NULL

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_conversationlog_failed_error_request_id"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "UPDATE core_conversationlog SET request_id = '' WHERE request_id IS NULL;",
                "ALTER TABLE core_conversationlog ALTER COLUMN request_id SET DEFAULT '';",
                "ALTER TABLE core_conversationlog ALTER COLUMN request_id SET NOT NULL;",
            ],
            reverse_sql=[
                "ALTER TABLE core_conversationlog ALTER COLUMN request_id DROP DEFAULT;",
            ],
        ),
    ]
