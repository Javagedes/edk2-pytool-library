# @file instanced_inf.py
# A module to run a table generator that uses a dsc and environment information to generate a table of information
# about instanced components and libraries where each row is a component or library
##
# Copyright (c) Microsoft Corporation
#
# SPDX-License-Identifier: BSD-2-Clause-Patent
##
"""A module to run the InstancedInf table generator against a dsc, adding instanced inf information to the database."""
import logging
import re
from pathlib import Path
from sqlite3 import Cursor

from edk2toollib.database.tables.base_table import TableGenerator
from edk2toollib.uefi.edk2.parsers.dsc_parser import DscParser as DscP
from edk2toollib.uefi.edk2.parsers.inf_parser import InfParser as InfP
from edk2toollib.uefi.edk2.path_utilities import Edk2Path

CREATE_INSTANCED_INF_TABLE = '''
CREATE TABLE IF NOT EXISTS instanced_inf (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    env INTEGER,
    dsc TEXT,
    path TEXT,
    name TEXT,
    arch TEXT,
    component TEXT,
    FOREIGN KEY(env) REFERENCES environment(env)
)
'''

INSERT_INSTANCED_INF_ROW = '''
INSERT INTO instanced_inf (env, dsc, path, name, arch, component)
VALUES (?, ?, ?, ?, ?, ?)
'''

INSERT_JUNCTION_ROW = '''
INSERT INTO junction (table1, key1, table2, key2)
VALUES (?, ?, ?, ?)
'''

GET_ROW_ID = '''
SELECT id FROM instanced_inf
WHERE env = ? and path = ? and dsc = ?
LIMIT 1
'''

class InstancedInfTable(TableGenerator):
    """A Table Generator that parses a single DSC file and generates a table."""
    SECTION_LIBRARY = "LibraryClasses"
    SECTION_COMPONENT = "Components"
    SECTION_REGEX = re.compile(r"\[(.*)\]")
    OVERRIDE_REGEX = re.compile(r"\<(.*)\>")

    def __init__(self, *args, **kwargs):
        """Initialize the query with the specific settings."""
        self.env = kwargs.pop("env")
        self.dsc = self.env["ACTIVE_PLATFORM"] # REQUIRED
        self.fdf = self.env.get("FLASH_DEFINITION", "")  # OPTIONAL
        self.arch = self.env["TARGET_ARCH"].split(" ")  # REQUIRED
        self.target = self.env["TARGET"]  # REQUIRED

    def create_tables(self, db_cursor: Cursor) -> None:
        """Create the tables necessary for this parser."""
        db_cursor.execute(CREATE_INSTANCED_INF_TABLE)

    def parse(self, db_cursor: Cursor, pathobj: Edk2Path) -> None:
        """Parse the workspace and update the database."""
        self.pathobj = pathobj
        self.ws = Path(self.pathobj.WorkspacePath)

        # Our DscParser subclass can now parse components, their scope, and their overrides
        dscp = DscP().SetEdk2Path(self.pathobj)
        dscp.SetInputVars(self.env)
        dscp.ParseFile(self.dsc)
        logging.debug(f"All DSCs included in {self.dsc}:")
        for dsc in dscp.GetAllDscPaths():
            logging.debug(f"  {dsc}")

        logging.debug("Fully expanded DSC:")
        for line in dscp.Lines:
            logging.debug(f"  {line}")
        logging.debug("End of DSC")

        # Create the instanced inf entries, including components and libraries. multiple entries
        # of the same library will exist if multiple components use it.
        #
        # This is where we merge DSC parser information with INF parser information.
        inf_entries = self._build_inf_table(dscp)
        for entry in inf_entries:
            if Path(entry["PATH"]).is_absolute():
                entry["PATH"] = self.pathobj.GetEdk2RelativePathFromAbsolutePath(entry["PATH"])

        env = db_cursor.execute("SELECT id FROM environment ORDER BY date DESC LIMIT 1").fetchone()[0]

        # add instanced_inf entries
        for entry in inf_entries:
            db_cursor.execute(
                INSERT_INSTANCED_INF_ROW,
                (env, entry["DSC"], entry["PATH"], entry["NAME"], entry["ARCH"], entry["COMPONENT"])
            )

        # add junction entries
        for entry in inf_entries:
            inf_id = db_cursor.execute(GET_ROW_ID, (env, entry["PATH"], entry["DSC"])).fetchone()[0]
            for source in entry["SOURCES_USED"]:
                db_cursor.execute(INSERT_JUNCTION_ROW, ("instanced_inf", inf_id, "source", source))
            for library in entry["LIBRARIES_USED"]:
                used_inf_id = db_cursor.execute(GET_ROW_ID, (env, library, entry["DSC"])).fetchone()[0]
                db_cursor.execute(INSERT_JUNCTION_ROW, ("instanced_inf", inf_id, "instanced_inf", used_inf_id))

    def _build_inf_table(self, dscp: DscP):

        inf_entries = []
        for (inf, scope, overrides) in dscp.Components:
            logging.debug(f"Parsing Component: [{inf}]")
            infp = InfP().SetEdk2Path(self.pathobj)
            infp.ParseFile(inf)

            # Libraries marked as a component only have source compiled and do not link against other libraries
            if "LIBRARY_CLASS" in infp.Dict:
                continue

            # scope for libraries need to contain the MODULE_TYPE also, so we will append it, if it exists
            if "MODULE_TYPE" in infp.Dict:
                scope += f".{infp.Dict['MODULE_TYPE']}".lower()

            inf_entries += self._parse_inf_recursively(inf, inf, dscp.ScopedLibraryDict, overrides, scope, [])

        # Move entries to correct table
        for entry in inf_entries:
            if entry["PATH"] == entry["COMPONENT"]:
                entry["COMPONENT"] = None

        return inf_entries

    def _parse_inf_recursively(
            self, inf: str, component: str, library_dict: dict, override_dict: dict, scope: str, visited):
        """Recurses down all libraries starting from a single INF.

        Will immediately return if the INF has already been visited.
        """
        logging.debug(f"  Parsing Library: [{inf}]")
        visited.append(inf)
        library_instances = []

        #
        # 0. Use the existing parser to parse the INF file. This parser parses an INF as an independent file
        #    and does not take into account the context of a DSC.
        #
        infp = InfP().SetEdk2Path(self.pathobj)
        infp.ParseFile(inf)

        #
        # 1. Convert all libraries to their actual instances for this component. This takes into account
        #    any overrides for this component
        #
        for lib in infp.get_libraries(self.arch):
            lib = lib.split(" ")[0].lower()
            library_instances.append(self._lib_to_instance(lib, scope, library_dict, override_dict))
        # Append all NULL library instances
        for null_lib in override_dict["NULL"]:
            if null_lib != inf:
                library_instances.append(null_lib)

        # Time to visit in libraries that we have not visited yet.
        to_return = []
        for library in filter(lambda lib: lib not in visited, library_instances):
            to_return += self._parse_inf_recursively(library, component,
                                                     library_dict, override_dict, scope, visited)

        # Return Paths as posix paths, which is Edk2 standard.
        to_return.append({
            "DSC": Path(self.dsc).name,
            "PATH": Path(inf).as_posix(),
            "GUID": infp.Dict.get("FILE_GUID", ""),
            "NAME": infp.Dict["BASE_NAME"],
            "COMPONENT": Path(component).as_posix(),
            "MODULE_TYPE": infp.Dict["MODULE_TYPE"],
            "ARCH": scope.split(".")[0].upper(),
            "SOURCES_USED": list(map(lambda p: Path(p).as_posix(), infp.Sources)),
            "LIBRARIES_USED": list(map(lambda p: Path(p).as_posix(), library_instances)),
            "PROTOCOLS_USED": [],  # TODO
            "GUIDS_USED": [],  # TODO
            "PPIS_USED": [],  # TODO
            "PCDS_USED": infp.PcdsUsed,
        })
        return to_return

    def _lib_to_instance(self, library_class_name, scope, library_dict, override_dict):
        """Converts a library name to the actual instance of the library.

        This conversion is based off the library section definitions in the DSC.
        """
        arch, module = tuple(scope.split("."))

        # https://tianocore-docs.github.io/edk2-DscSpecification/release-1.28/2_dsc_overview/27_[libraryclasses]_section_processing.html#27-libraryclasses-section-processing

        # 1. If a Library class instance (INF) is specified in the Edk2 II [Components] section (an override),
        #    then it will be used
        if library_class_name in override_dict:
            return override_dict[library_class_name]

        # 2/3. If the Library Class instance (INF) is defined in the [LibraryClasses.$(ARCH).$(MODULE_TYPE)] section,
        #    then it will be used.
        lookup = f'{arch}.{module}.{library_class_name}'
        if lookup in library_dict:
            return library_dict[lookup]

        # 4. If the Library Class instance (INF) is defined in the [LibraryClasses.common.$(MODULE_TYPE)] section,
        #   then it will be used.
        lookup = f'common.{module}.{library_class_name}'
        if lookup in library_dict:
            return library_dict[lookup]

        # 5. If the Library Class instance (INF) is defined in the [LibraryClasses.$(ARCH)] section,
        #    then it will be used.
        lookup = f'{arch}.{library_class_name}'
        if lookup in library_dict:
            return library_dict[lookup]

        # 6. If the Library Class Instance (INF) is defined in the [LibraryClasses] section,
        #    then it will be used.
        lookup = f'common.{library_class_name}'
        if lookup in library_dict:
            return library_dict[lookup]

        logging.debug(f'scoped library contents: {library_dict}')
        logging.debug(f'override dictionary: {override_dict}')
        e = f'Cannot find library class [{library_class_name}] for scope [{scope}] when evaluating {self.dsc}'
        logging.error(e)
        raise RuntimeError(e)
