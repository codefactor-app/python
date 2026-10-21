"""Forward the complete core CLI without interpreting arguments or reports."""
import errno
import os
import subprocess
import sys
from ._core import ConfigError, argument_context, resolve_binary, update_command


def main() -> int:
    try:
        if sys.argv[1:2] == ['core']:
            return update_command(sys.argv[2:])
        binary = str(resolve_binary(**argument_context(sys.argv[1:])))
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 3 if isinstance(error, ConfigError) else 1
    command = [binary, *sys.argv[1:]]
    try:
        if os.name != "nt":
            os.execv(binary, command)
        return subprocess.call(command)
    except OSError as error:
        print(f"Cannot start Codefactor binary: {error}. Run codefactor core update or check CODEFACTOR_BINARY.", file=sys.stderr)
        return 127 if error.errno == errno.ENOENT else 126
    except KeyboardInterrupt:
        return 130
