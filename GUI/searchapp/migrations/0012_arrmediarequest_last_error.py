from django.db import migrations, models


def explain_import_pending(apps, schema_editor):
    apps.get_model("searchapp", "ArrMediaRequest").objects.filter(status="import_pending").update(last_error="import_not_confirmed")


class Migration(migrations.Migration):
    dependencies = [("searchapp", "0011_arrlanguagecheck_source_url")]
    operations = [
        migrations.AddField(
            model_name="arrmediarequest",
            name="last_error",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.RunPython(explain_import_pending, migrations.RunPython.noop),
    ]
