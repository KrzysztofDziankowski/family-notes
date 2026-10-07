"""Disposable, forward-only migration databases using the configured backend."""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.db import connections
from django.db.migrations.executor import MigrationExecutor


@contextmanager
def migration_database():
    alias = 'migration_' + uuid4().hex
    config = deepcopy(connections['default'].settings_dict)
    with TemporaryDirectory(prefix='family-notes-migration-') as directory:
        config['TEST']['MIRROR'] = None
        config['TEST']['NAME'] = (
            str(Path(directory) / 'migration.sqlite3')
            if connections['default'].vendor == 'sqlite'
            else 'test_fn_migration_' + uuid4().hex
        )
        connections.databases[alias] = config
        database = connections[alias]
        original_name = config['NAME']
        created = False
        try:
            # create_test_db() would apply the latest migrations first; create
            # only the empty database, then let each scenario migrate forward.
            name = database.creation._create_test_db(verbosity=0, autoclobber=True)
            database.close()
            database.settings_dict['NAME'] = name
            created = True
            yield database
        finally:
            try:
                if created:
                    database.creation.destroy_test_db(old_database_name=original_name, verbosity=0)
            finally:
                database.close()
                del connections[alias]
                connections.databases.pop(alias, None)


def migrate(database, target):
    executor = MigrationExecutor(database)
    executor.migrate(target)
    return executor.loader.project_state(target).apps
