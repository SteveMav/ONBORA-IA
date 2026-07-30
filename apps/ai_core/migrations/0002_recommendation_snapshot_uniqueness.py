from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_core", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="recommendationrecord",
            name="unique_recommendation_fingerprint",
        ),
        migrations.AddConstraint(
            model_name="recommendationrecord",
            constraint=models.UniqueConstraint(
                fields=("profile_snapshot", "input_fingerprint"),
                name="unique_recommendation_fingerprint",
            ),
        ),
    ]
