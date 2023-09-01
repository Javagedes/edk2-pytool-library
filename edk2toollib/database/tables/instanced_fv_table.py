# @file instaced_fv.py
# A module to run a table generator that uses a fdf and environment information to generate a table of information
# about instanced fvs where each row is a unique fv.
##
# Copyright (c) Microsoft Corporation
#
# SPDX-License-Identifier: BSD-2-Clause-Patent
##
"""A module to generate a table containing fv information."""
import sqlite3
from pathlib import Path

from edk2toollib.database.tables.base_table import TableGenerator
from edk2toollib.uefi.edk2.parsers.fdf_parser import FdfParser as FdfP
from edk2toollib.uefi.edk2.path_utilities import Edk2Path

CREATE_INSTANCED_FV_TABLE = """
CREATE TABLE IF NOT EXISTS instanced_fv (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    env INTEGER,
    fv_name TEXT,
    fdf TEXT,
    path TEXT
)
"""

INSERT_INSTANCED_FV_ROW = """
INSERT INTO instanced_fv (env, fv_name, fdf, path)
VALUES (?, ?, ?, ?)
"""

INSERT_JUNCTION_ROW = '''
INSERT INTO junction (table1, key1, table2, key2)
VALUES (?, ?, ?, ?)
'''

class InstancedFvTable(TableGenerator):
    """A Table Generator that parses a single FDF file and generates a table containing FV information."""  # noqa: E501
    def __init__(self, *args, **kwargs):
        """Initialize the query with the specific settings."""
        self.env = kwargs.pop("env")
        self.dsc = self.env["ACTIVE_PLATFORM"]
        self.fdf = self.env["FLASH_DEFINITION"]
        self.arch = self.env["TARGET_ARCH"].split(" ")
        self.target = self.env["TARGET"]

    def create_tables(self, db_cursor: sqlite3.Cursor) -> None:
        """Create the tables necessary for this parser."""
        db_cursor.execute(CREATE_INSTANCED_FV_TABLE)

    def parse(self, db_cursor: sqlite3.Cursor, pathobj: Edk2Path) -> None:
        """Parse the workspace and update the database."""
        self.pathobj = pathobj
        self.ws = Path(self.pathobj.WorkspacePath)

        # Our DscParser subclass can now parse components, their scope, and their overrides
        fdfp = FdfP().SetEdk2Path(self.pathobj)
        fdfp.SetInputVars(self.env)
        fdfp.ParseFile(self.fdf)

        env = db_cursor.execute("SELECT id FROM environment ORDER BY date DESC LIMIT 1").fetchone()[0]
        for fv in fdfp.FVs:

            inf_list = []  # Some INF's start with RuleOverride. We only need the INF
            for inf in fdfp.FVs[fv]["Infs"]:
                if inf.lower().startswith("ruleoverride"):
                    inf = inf.split(" ", 1)[-1]
                if Path(inf).is_absolute():
                    inf = str(Path(self.pathobj.GetEdk2RelativePathFromAbsolutePath(inf)))
                inf_list.append(Path(inf).as_posix())

            db_cursor.execute(INSERT_INSTANCED_FV_ROW, (env, fv, Path(self.fdf).name, self.fdf))
            fv_id = db_cursor.lastrowid
            for inf in inf_list:
                db_cursor.execute(INSERT_JUNCTION_ROW, ("instanced_fv", fv_id, "inf", inf))
