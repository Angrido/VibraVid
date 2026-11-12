from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("searchapp", "0011_arrlanguagecheck_source_url")]
    operations = [
        migrations.AddField(
            model_name="arrmediarequest",
            name="last_error",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
    ]
