#!/usr/bin/env python3

import compileall
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    ok = compileall.compile_dir(str(ROOT / "src"), quiet=1)
    ok = compileall.compile_dir(str(ROOT / "bin"), quiet=1) and ok
    ok = compileall.compile_dir(str(ROOT / "scripts"), quiet=1) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
