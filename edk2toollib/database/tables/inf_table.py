# @file inf_table.py
# A module to run a table generator that parses all INF files in the workspace and generates a table of information
# about each INF.
##
# Copyright (c) Microsoft Corporation
#
# SPDX-License-Identifier: BSD-2-Clause-Patent
##
"""A module to run generate a table containing information about each INF in the workspace."""
import logging
import time
from pathlib import Path
from sqlite3 import Cursor

import git
from joblib import Parallel, delayed

from edk2toollib.database.tables.base_table import TableGenerator
from edk2toollib.uefi.edk2.parsers.inf_parser import InfParser as InfP
from edk2toollib.uefi.edk2.path_utilities import Edk2Path

CREATE_INF_TABLE = '''
CREATE TABLE IF NOT EXISTS inf (
    path TEXT PRIMARY KEY,
    guid TEXT,
    library_class TEXT,
    repo TEXT
);
'''

CREATE_LIBRARY_CLASS_TABLE = '''
CREATE TABLE IF NOT EXISTS library_class (
    class TEXT
)
'''

INSERT_JUNCTION_ROW = '''
INSERT INTO junction (table1, key1, table2, key2)
VALUES (?, ?, ?, ?)
'''

INSERT_INF_ROW = '''
INSERT OR REPLACE INTO inf (path, guid, library_class, repo)
VALUES (?, ?, ?, ?)
'''

class InfTable(TableGenerator):
    """A Table Generator that parses all INF files in the workspace and generates a table."""
    # TODO: Add phase, protocol, guid, ppi, pcd tables and associations once necessary
    def __init__(self, *args, **kwargs):
        """Initializes the INF Table Parser.

        Args:
            args (any): non-keyword arguments
            kwargs (any): keyword arguments described below

        Keyword Arguments:
            n_jobs (int): Number of files to run in parallel
        """
        self.n_jobs = kwargs.get("n_jobs", -1)

    def create_tables(self, db_cursor: Cursor) -> None:
        """Create the tables necessary for this parser."""
        db_cursor.execute(CREATE_INF_TABLE)
        db_cursor.execute(CREATE_LIBRARY_CLASS_TABLE)

    def parse(self, db_cursor: Cursor, pathobj: Edk2Path) -> None:
        """Parse the workspace and update the database."""
        ws = Path(pathobj.WorkspacePath)
        inf_entries = []
        try:
            repo = git.Repo(ws)
        except git.InvalidGitRepositoryError:
            repo = None

        start = time.time()
        files = list(ws.glob("**/*.inf"))
        files = [file for file in files if not file.is_relative_to(ws / "Build")]
        inf_entries = Parallel(n_jobs=self.n_jobs)(delayed(self._parse_file)(repo, fname, pathobj) for fname in files)
        logging.debug(
            f"{self.__class__.__name__}: Parsed {len(inf_entries)} .inf files took; "
            f"{round(time.time() - start, 2)} seconds.")

        for inf_entry in inf_entries:
            db_cursor.execute(
                INSERT_INF_ROW,
                (inf_entry["PATH"], inf_entry["GUID"], inf_entry["LIBRARY_CLASS"], inf_entry["REPO"])
            )
            for library in inf_entry["LIBRARIES_USED"]:
                db_cursor.execute(INSERT_JUNCTION_ROW, ("inf", inf_entry["PATH"], "library_class", library))
            for source in inf_entry["SOURCES_USED"]:
                db_cursor.execute(INSERT_JUNCTION_ROW, ("inf", inf_entry["PATH"], "source", source))

    def _parse_file(self, repo, filename, pathobj) -> dict:
        inf_parser = InfP().SetEdk2Path(pathobj)
        inf_parser.ParseFile(filename)

        containing_repo = "BASE"
        if repo:
            for submodule in repo.submodules:
                if submodule.abspath in str(filename):
                    containing_repo = submodule.name
                    break

        pkg = pathobj.GetContainingPackage(str(inf_parser.Path))
        path = Path(inf_parser.Path).as_posix()
        if pkg:
            path = path[path.find(pkg):]
        data = {}
        data["GUID"] = inf_parser.Dict.get("FILE_GUID", "")
        data["LIBRARY_CLASS"] = inf_parser.LibraryClass
        data["PATH"] = Path(path).as_posix()
        data["PHASES"] = inf_parser.SupportedPhases
        data["SOURCES_USED"] = inf_parser.Sources
        data["BINARIES_USED"] = inf_parser.Binaries
        data["LIBRARIES_USED"] = inf_parser.LibrariesUsed
        data["PROTOCOLS_USED"] = inf_parser.ProtocolsUsed
        data["GUIDS_USED"] = inf_parser.GuidsUsed
        data["PPIS_USED"] = inf_parser.PpisUsed
        data["PCDS_USED"] = inf_parser.PcdsUsed
        data["REPO"] = containing_repo

        return data
