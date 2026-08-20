from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0131_geocustomzone_description"),
    ]

    operations = [
        migrations.AddField(
            model_name="geocustomzonecategory",
            name="description",
            field=models.TextField(blank=True, null=True),
        ),
    ]
