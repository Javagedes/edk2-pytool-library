# @file edk2_db.py
# A class for interacting with a database implemented using json.
##
# Copyright (c) Microsoft Corporation
#
# SPDX-License-Identifier: BSD-2-Clause-Patent
##
"""A class for interacting with a database implemented using json."""
import logging
import sqlite3
import time
from typing import Any

from edk2toollib.uefi.edk2.path_utilities import Edk2Path

from edk2toollib.database.tables.base_table import TableGenerator

CREATE_JUNCTION_TABLE = """
CREATE TABLE IF NOT EXISTS junction (
    table1 TEXT,
    key1 TEXT,
    table2 TEXT,
    key2 TEXT
)
"""

class Edk2DB:
    """A SQLite3 database manager for a EDKII workspace.

    This class provides the ability to register parsers that will create / update tables in the database while also
    providing the ability to run queries on the database.

    Edk2DB can, and should, be used as a context manager to ensure that the database is closed properly. If
    not using as a context manager, the `close()` method must be used to ensure that the database is closed properly
    and any changes are saved.

    When running the parse() command, the user can specify whether or not to append the results to the database. If
    not appending to the database, the entire database will be dropped before parsing.

    ```python
    from edk2toollib.database.parsers import *
    with Edk2DB(Path("path/to/db.db"), edk2path) as db:
        db.register(Parser1(), Parser2(), Parser3())
        db.parse()
   """
    def __init__(self, db_path: str, pathobj: Edk2Path, **kwargs: dict[str,Any]):
        """Initializes the database.

        Args:
            db_path: Path to create or load the database from
            pathobj: Edk2Path object for the workspace
            **kwargs: see Keyword Arguments

        Keyword Arguments:
            None
        """
        self.pathobj = pathobj
        self._parsers = []
        self.connection = sqlite3.connect(db_path)

    def __enter__(self):
        """Enables the use of the `with` statement."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Enables the use of the `with` statement."""
        self.connection.commit()
        self.connection.close()

    def register(self, *parsers: 'TableGenerator') -> None:
        """Registers a one or more table generators.

        Args:
            *parsers: One or more instantiated TableGenerator object
        """
        for parser in parsers:
            self._parsers.append(parser)

    def clear_parsers(self) -> None:
        """Empties the list of registered table generators."""
        self._parsers = []

    def parse(self) -> None:
        """Runs all registered table parsers against the database."""
        # Create the junction table
        self.connection.execute(CREATE_JUNCTION_TABLE)

        # Create all tables
        for parser in self._parsers:
            parser.create_tables(self.connection.cursor())

        # Fill all tables
        for parser in self._parsers:
            logging.debug(f"[{parser.__class__.__name__}] starting...")
            time.time()
            parser.parse(self.connection.cursor(), self.pathobj)
            self.connection.commit()
