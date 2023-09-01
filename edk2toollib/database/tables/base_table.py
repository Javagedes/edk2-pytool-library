import sqlite3

from edk2toollib.uefi.edk2.path_utilities import Edk2Path


class TableGenerator:
    """An interface for a parser that Generates an Edk2DB table.

    Allows you to parse a workspace, file, etc, and load the contents into the database as rows in a table.

    Edk2Db provides a connection to a sqlite3 database and will commit any changes made during `parse` once
    the parser has finished executing and has returned. Review sqlite3 documentation for more information on
    how to interact with the database.
    """
    def __init__(self, *args, **kwargs):
        """Initialize the query with the specific settings."""

    def create_tables(self, db_cursor: sqlite3.Cursor) -> None:
        """Create the tables necessary for this parser."""
        raise NotImplementedError

    def parse(self, db_cursor: sqlite3.Cursor, pathobj: Edk2Path) -> None:
        """Execute the parser and update the database."""
        raise NotImplementedError
