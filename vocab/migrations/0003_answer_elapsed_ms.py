from django.db import migrations, models

TABLE = "vocab_answer"
COLUMN = "elapsed_ms"


def add_column_if_missing(apps, schema_editor):
    """Add elapsed_ms, unless an older schema already left the column behind.

    Databases created by earlier versions of this project can already carry a
    NOT NULL elapsed_ms column. Adding it again would fail, so the column is
    only created when it is genuinely absent; either way the model and the
    table end up agreeing.
    """
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        existing = {
            column.name for column in connection.introspection.get_table_description(cursor, TABLE)
        }
    if COLUMN in existing:
        return

    field = models.PositiveIntegerField(default=0)
    field.set_attributes_from_name(COLUMN)
    schema_editor.add_field(apps.get_model("vocab", "Answer"), field)


def drop_column(apps, schema_editor):
    field = models.PositiveIntegerField(default=0)
    field.set_attributes_from_name(COLUMN)
    schema_editor.remove_field(apps.get_model("vocab", "Answer"), field)


class Migration(migrations.Migration):

    dependencies = [
        ("vocab", "0002_testsession_timings"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="answer",
                    name="elapsed_ms",
                    field=models.PositiveIntegerField(default=0),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_column_if_missing, drop_column),
            ],
        ),
    ]
