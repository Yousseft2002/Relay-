"""Launch the source-checkout bridge from any working directory."""
import sys
from pathlib import Path

from relay.bridge import main


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    sys.exit(main(["--state-dir", str(root / ".relay" / "state" / "bridge"),
                   *sys.argv[1:]]))
