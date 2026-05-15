from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0116_useractionlog"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tileset",
            name="date",
            field=models.DateField(),
        ),
    ]
