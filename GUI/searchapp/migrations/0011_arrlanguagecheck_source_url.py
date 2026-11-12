from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("searchapp", "0010_arrlanguagecheck")]
    operations = [
        migrations.AddField(
            model_name="arrlanguagecheck",
            name="source_url",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
    ]
