# Generated by Django 5.0.6 on 2024-07-03 13:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0039_remove_tileset_communes_remove_tileset_departments_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='detectiondata',
            name='detection_control_status',
            field=models.CharField(choices=[('DETECTED', 'DETECTED'), ('SIGNALED_INTERNALLY', 'SIGNALED_INTERNALLY'), ('SIGNALED_COLLECTIVITY', 'SIGNALED_COLLECTIVITY'), ('CONFIRMED_FIELD', 'CONFIRMED_FIELD'), ('INVALIDATED_FIELD', 'INVALIDATED_FIELD')], max_length=255),
        ),
        migrations.AlterField(
            model_name='detectiondata',
            name='detection_validation_status',
            field=models.CharField(choices=[('DETECTED_NOT_VERIFIED', 'DETECTED_NOT_VERIFIED'), ('SUSPECT', 'SUSPECT'), ('LEGITIMATE', 'LEGITIMATE'), ('INVALIDATED', 'INVALIDATED'), ('CONTROLLED', 'CONTROLLED')], max_length=255),
        ),
        migrations.AddIndex(
            model_name='geozone',
            index=models.Index(fields=['id'], name='idx_geozone_id'),
        ),
        migrations.AddIndex(
            model_name='userusergroup',
            index=models.Index(fields=['user_id', 'user_group_id'], name='idx_user_group_id'),
        ),
    ]