# Generated manually for v2 ConversationLog fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_conversationlog_agents_involved_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversationlog",
            name="error_message",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="conversationlog",
            name="request_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AlterField(
            model_name="conversationlog",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("in_progress", "In Progress"),
                    ("resolved", "Resolved"),
                    ("escalated", "Escalated"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
