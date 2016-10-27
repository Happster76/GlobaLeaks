# -*- coding: UTF-8
# orm: contains main hooks to storm ORM
# ******
import sys
import transaction

from storm import exceptions, tracer
import storm.databases.sqlite
from storm.databases.sqlite import sqlite
from storm.zope.zstorm import ZStorm


from twisted.internet import reactor
from twisted.internet.threads import deferToThreadPool

from globaleaks.settings import GLSettings


class SQLite(storm.databases.sqlite.Database):
    connection_factory = storm.databases.sqlite.SQLiteConnection

    def __init__(self, uri):
        if sqlite is storm.databases.sqlite.dummy:
            raise storm.databases.sqlite.DatabaseModuleError("'pysqlite2' module not found")
        self._filename = uri.database or ":memory:"
        self._timeout = float(uri.options.get("timeout", 5))
        self._synchronous = uri.options.get("synchronous")
        self._journal_mode = uri.options.get("journal_mode")
        self._foreign_keys = uri.options.get("foreign_keys")

        self.raw_connect().execute("VACUUM")

    def raw_connect(self):
        raw_connection = sqlite.connect(self._filename, timeout=self._timeout,
                                        isolation_level=None)

        if self._synchronous is not None:
            raw_connection.execute("PRAGMA synchronous = %s" %
                                   (self._synchronous,))

        if self._journal_mode is not None:
            raw_connection.execute("PRAGMA journal_mode = %s" %
                                   (self._journal_mode,))

        if self._foreign_keys is not None:
            raw_connection.execute("PRAGMA foreign_keys = %s" %
                                   (self._foreign_keys,))

        raw_connection.execute("PRAGMA secure_delete = ON") # = 1

        return raw_connection

storm.databases.sqlite.SQLite = SQLite
storm.databases.sqlite.create_from_uri = SQLite
# XXX. END MONKEYPATCH


def get_store():
    """
    Returns a reference to Storm Store
    """
    zstorm = ZStorm()
    zstorm.set_default_uri(GLSettings.store_name, GLSettings.db_uri)

    return zstorm.get(GLSettings.store_name)


class transact(object):
    """
    Class decorator for managing transactions.
    Because Storm sucks.
    """
    readonly = False
    synchronous = False

    def __init__(self, method):
        self.method = method
        self.instance = None
        self.debug = GLSettings.orm_debug

        if self.debug:
            tracer.debug(self.debug, sys.stdout)

    def __get__(self, instance, owner):
        self.instance = instance
        return self

    def __call__(self, *args, **kwargs):
        return self.run(self._wrap, self.method, *args, **kwargs)

    def run(self, function, *args, **kwargs):
        return deferToThreadPool(reactor,
                                 GLSettings.orm_tp,
                                 function,
                                 *args,
                                 **kwargs)

    def _wrap(self, function, *args, **kwargs):
        """
        Wrap provided function calling it inside a thread and
        passing the store to it.
        """
        store = get_store()

        try:
            if self.instance:
                result = function(self.instance, store, *args, **kwargs)
            else:
                result = function(store, *args, **kwargs)

            if not self.readonly:
                store.commit()
        except:
            store.rollback()
            transaction.abort()
            raise
        finally:
            store._cache.clear()
            store.close()

        transaction.commit()

        return result


class transact_ro(transact):
    readonly = True


class transact_sync(transact):
    def run(self, function, *args, **kwargs):
        return function(*args, **kwargs)


class transact_sync_ro(transact_sync):
    readonly = True
