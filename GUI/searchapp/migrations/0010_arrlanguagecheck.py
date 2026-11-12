from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("searchapp", "0009_arrprocessingqueue_attempts")]
    operations = [
        migrations.CreateModel(
            name="ArrLanguageCheck",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("media_key", models.CharField(max_length=64, unique=True)),
                ("title_key", models.CharField(db_index=True, max_length=64)),
                ("verdict", models.CharField(choices=[("available", "Available"), ("absent", "Absent"), ("unknown", "Unknown"), ("not_found", "Not found"), ("failed", "Failed")], max_length=16)),
                ("languages", models.JSONField(blank=True, default=list)),
                ("provider", models.CharField(blank=True, default="", max_length=100)),
                ("checked_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
