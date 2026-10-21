"""Forward the complete core CLI without interpreting arguments or reports."""
import errno
import os
import subprocess
import sys
from ._installer import binary_path


def main() -> int:
    binary = os.environ.get("CODEFACTOR_BINARY") or str(binary_path())
    command = [binary, *sys.argv[1:]]
    try:
        if os.name != "nt":
            os.execv(binary, command)
        return subprocess.call(command)
    except OSError as error:
        print(f"Cannot start Codefactor binary: {error}. Reinstall the package or set CODEFACTOR_BINARY.", file=sys.stderr)
        return 127 if error.errno == errno.ENOENT else 126
    except KeyboardInterrupt:
        return 130
