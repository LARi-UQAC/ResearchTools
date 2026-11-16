"""
list_test_ids - the unittest ids of one test file, one per line, so a runner can cut a slow suite into
several processes (scripts/test/run-offline-tests.ps1, Issue #120).

Usage: python list_test_ids.py FILE

Each line is `Class.test_name`, the form a test file ending in `unittest.main()` accepts on its command line
(`python FILE Class.test_name ...` runs only those tests). Exit codes: 0 ids printed, 1 the file could not be
imported, 2 the file does not exist or no test was found.
"""
import importlib.util
import sys
import unittest
from pathlib import Path
from typing import List


def _flatten(suite: unittest.TestSuite) -> List[unittest.TestCase]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a nested test suite into the list of its test cases, in order.
    Inputs:
        suite (unittest.TestSuite): a suite as the loader builds it
    Outputs:
        cases (list): the test cases
    --------------------------------------------------------------------------
    """
    cases: List[unittest.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            cases.extend(_flatten(item))
        else:
            cases.append(item)
    return cases


def list_ids(path: Path) -> List[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the test ids of a test file without running any test.
    Details:
        The file is imported under its own stem as module name, with its folder on the path, which is how the
        suites of this repository import their neighbours. A module that cannot be imported raises.
    Inputs:
        path (Path): a test file
    Outputs:
        ids (list[str]): `Class.test_name`, in file order, without the module prefix
    Raises:
        ImportError, SyntaxError or any error the module raises when it is imported.
    --------------------------------------------------------------------------
    """
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    prefix = path.stem + "."
    return [case.id()[len(prefix):] if case.id().startswith(prefix) else case.id() for case in _flatten(suite)]


def main(argv: List[str]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Print the ids of the test file named on the command line.
    Inputs:
        argv (list[str]): the file path
    Outputs:
        code (int): 0 ids printed, 1 import failure, 2 no such file or no test (nothing printed)
    --------------------------------------------------------------------------
    """
    if len(argv) != 1 or not Path(argv[0]).is_file():
        print("usage: list_test_ids.py FILE (an existing test file)", file=sys.stderr)
        return 2
    try:
        ids = list_ids(Path(argv[0]).resolve())
    except Exception as error:  # a suite that cannot be imported is run whole by the caller
        print("cannot import %s: %s" % (Path(argv[0]).name, error.__class__.__name__), file=sys.stderr)
        return 1
    if not ids:
        print("no test found in %s" % Path(argv[0]).name, file=sys.stderr)
        return 2
    # Suites may print while they are imported: only the ids are marked, so the caller can tell them apart.
    for test_id in ids:
        print("TESTID " + test_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
