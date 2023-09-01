##
# unittests for the InstancedInfTable generator
#
# Copyright (c) Microsoft Corporation
#
# SPDX-License-Identifier: BSD-2-Clause-Patent
##
# ruff: noqa: F811
"""unittests for the InfTable generator."""
import logging
from pathlib import Path

import pytest
from common import Tree, empty_tree  # noqa: F401
from edk2toollib.database import Edk2DB
from edk2toollib.database.tables import EnvironmentTable, InstancedInfTable
from edk2toollib.uefi.edk2.path_utilities import Edk2Path

GET_USED_LIBRARIES_QUERY = """
SELECT i.path
FROM instanced_inf AS i
JOIN junction AS j ON i.id = j.key2 and j.table2 = "instanced_inf"
WHERE j.key1 = (
    SELECT id
    FROM instanced_inf
    WHERE name = ? AND arch = ?
    LIMIT 1
);
"""

def test_valid_dsc(empty_tree: Tree):
    """Tests that a typical dsc can be correctly parsed."""
    edk2path = Edk2Path(str(empty_tree.ws), [])
    db = Edk2DB(empty_tree.ws / "db.db", pathobj=edk2path)
    db.register(EnvironmentTable())

    comp1 = empty_tree.create_component("TestComponent1", "DXE_DRIVER")
    lib1 = empty_tree.create_library("TestLib1", "TestCls")
    dsc = empty_tree.create_dsc(
        libraryclasses = [lib1],
        components = [str(empty_tree.ws / comp1), lib1]  # absolute comp path
    )

    inf_table = InstancedInfTable(env = {
        "ACTIVE_PLATFORM": dsc,
        "TARGET_ARCH": "IA32",
        "TARGET": "DEBUG",
    })
    db.register(inf_table)
    db.parse()

    rows = db.connection.cursor().execute("SELECT * FROM instanced_inf").fetchall()
    assert len(rows) == 1
    assert rows[0][4] == Path(comp1).stem

def test_no_active_platform(empty_tree: Tree, caplog):
    """Tests that the dsc table returns immediately when no ACTIVE_PLATFORM is defined."""
    caplog.set_level(logging.DEBUG)
    edk2path = Edk2Path(str(empty_tree.ws), [])
    db = Edk2DB(empty_tree.ws / "db.db", pathobj=edk2path)
    db.register(EnvironmentTable())

    # Test 1: raise error for missing ACTIVE_PLATFORM
    with pytest.raises(KeyError, match = "ACTIVE_PLATFORM"):
        InstancedInfTable(env = {})

    # Test 2: raise error for missing TARGET_ARCH
    with pytest.raises(KeyError, match = "TARGET_ARCH"):
        InstancedInfTable(env = {
            "ACTIVE_PLATFORM": "Test.dsc"
        })

    # Test 3: raise error for missing TARGET
    with pytest.raises(KeyError, match = "TARGET"):
        InstancedInfTable(env = {
            "ACTIVE_PLATFORM": "Test.dsc",
            "TARGET_ARCH": "IA32",
        })

def test_dsc_with_conditional(empty_tree: Tree):
    """Tests that conditionals inside a DSC works as expected."""
    edk2path = Edk2Path(str(empty_tree.ws), [])
    db = Edk2DB(empty_tree.ws / "db.db", pathobj=edk2path)
    db.register(EnvironmentTable())

    empty_tree.create_library("TestLib", "SortLib")
    comp1 = empty_tree.create_component('TestComponent1', 'DXE_DRIVER')

    dsc = empty_tree.create_dsc(
        components = [
            "!if $(TARGET) == \"RELEASE\"",
            f"{comp1}",
            "!endif"
    ])

    inf_table = InstancedInfTable(env = {
        "ACTIVE_PLATFORM": dsc,
        "TARGET_ARCH": "IA32 X64",
        "TARGET": "DEBUG",
    })
    db.register(inf_table)
    db.parse()

    assert db.connection.cursor().execute("SELECT * FROM instanced_inf").fetchall() == []

def test_library_override(empty_tree: Tree):
    """Tests that overrides and null library overrides can be parsed as expected."""
    edk2path = Edk2Path(str(empty_tree.ws), [])
    db = Edk2DB(empty_tree.ws / "db.db", pathobj=edk2path)
    db.register(EnvironmentTable())

    lib1 = empty_tree.create_library("TestLib1", "TestCls")
    lib2 = empty_tree.create_library("TestLib2", "TestCls")
    lib3 = empty_tree.create_library("TestLib3", "TestNullCls")

    comp1 = empty_tree.create_component(
        "TestDriver1", "DXE_DRIVER",
        libraryclasses = ["TestCls"]
    )

    dsc = empty_tree.create_dsc(
        libraryclasses = [
            f'TestCls|{lib1}',
        ],
        components = [
            f'{comp1} {{',
            '<LibraryClasses>',
            '!if $(TARGET) == "DEBUG"',
            f'TestCls|{lib2}',
            f'NULL|{lib3}',
            '!endif',
            '}',
        ]
    )

    inf_table = InstancedInfTable(env = {
        "ACTIVE_PLATFORM": dsc,
        "TARGET_ARCH": "IA32 X64",
        "TARGET": "DEBUG",
    })
    db.register(inf_table)
    db.parse()
    db.connection.execute("SELECT * FROM junction").fetchall()
    library_list = db.connection.cursor().execute(GET_USED_LIBRARIES_QUERY, ("TestDriver1", "IA32"))

    for path, in library_list:
        assert path in [lib2, lib3]

def test_scoped_libraries1(empty_tree: Tree):
    """Ensure that the correct libraries in regards to scoping.

    Checks proper usage of:

    1. $(ARCH).$(MODULE)
    2. $(ARCH)
    """
    edk2path = Edk2Path(str(empty_tree.ws), [])
    db = Edk2DB(empty_tree.ws / "db.db", pathobj=edk2path)
    db.register(EnvironmentTable())

    lib1 = empty_tree.create_library("TestLib1", "TestCls")
    lib2 = empty_tree.create_library("TestLib2", "TestCls")
    lib3 = empty_tree.create_library("TestLib3", "TestCls")

    comp1 = empty_tree.create_component("TestDriver1", "PEIM", libraryclasses = ["TestCls"])
    comp2 = empty_tree.create_component("TestDriver2", "SEC", libraryclasses = ["TestCls"])
    comp3 = empty_tree.create_component("TestDriver3", "PEIM", libraryclasses = ["TestCls"])

    dsc = empty_tree.create_dsc(
        libraryclasses = [f'TestCls|{lib1}'],
        libraryclasses_ia32 = [f'TestCls|{lib2}'],
        libraryclasses_ia32_peim = [f'TestCls|{lib3}'],
        components = [],
        components_x64 = [comp1],
        components_ia32 = [comp2, comp3]
    )

    inf_table = InstancedInfTable(env = {
        "ACTIVE_PLATFORM": dsc,
        "TARGET_ARCH": "IA32 X64",
        "TARGET": "DEBUG",
    })
    db.register(inf_table)
    db.parse()

    for arch in ["IA32", "X64"]:
        for component, in db.connection.execute("SELECT name FROM instanced_inf WHERE component IS NULL and arch is ?;", (arch,)):
            component_lib = db.connection.execute(GET_USED_LIBRARIES_QUERY, (component, arch)).fetchone()[0]
            assert component.replace("Driver", "Lib") in component_lib

def test_scoped_libraries2(empty_tree: Tree):
    """Ensure that the correct libraries in regards to scoping.

    Checks proper usage of:

    1. common.$(MODULE)
    2. common
    """
    edk2path = Edk2Path(str(empty_tree.ws), [])
    db = Edk2DB(empty_tree.ws / "db.db", pathobj=edk2path)
    db.register(EnvironmentTable())

    lib1 = empty_tree.create_library("TestLib1", "TestCls")
    lib2 = empty_tree.create_library("TestLib2", "TestCls")

    comp1 = empty_tree.create_component("TestDriver1", "PEIM", libraryclasses = ["TestCls"])
    comp2 = empty_tree.create_component("TestDriver2", "SEC", libraryclasses = ["TestCls"])

    dsc = empty_tree.create_dsc(
        libraryclasses_common_peim = [f'TestCls|{lib1}'],
        libraryclasses = [f'TestCls|{lib2}'],
        components = [],
        components_x64 = [comp1, comp2],
    )

    inf_table = InstancedInfTable(env = {
        "ACTIVE_PLATFORM": dsc,
        "TARGET_ARCH": "IA32 X64",
        "TARGET": "DEBUG",
    })
    db.register(inf_table)
    db.parse()

    for arch in ["IA32", "X64"]:
        for component, in db.connection.execute("SELECT name FROM instanced_inf WHERE component IS NULL and arch is ?;", (arch,)):
            component_lib = db.connection.execute(GET_USED_LIBRARIES_QUERY, (component, arch)).fetchone()[0]
            assert component.replace("Driver", "Lib") in component_lib

def test_missing_library(empty_tree: Tree):
    """Test when a library is missing."""
    edk2path = Edk2Path(str(empty_tree.ws), [])
    db = Edk2DB(empty_tree.ws / "db.db", pathobj=edk2path)
    db.register(EnvironmentTable())

    comp1 = empty_tree.create_component("TestDriver1", "PEIM", libraryclasses = ["TestCls"])

    dsc = empty_tree.create_dsc(
        libraryclasses = [],
        components = [],
        components_x64 = [comp1],
    )

    inf_table = InstancedInfTable(env = {
        "ACTIVE_PLATFORM": dsc,
        "TARGET_ARCH": "IA32 X64",
        "TARGET": "DEBUG",
    })
    db.register(inf_table)
    with pytest.raises(RuntimeError):
        db.parse()
