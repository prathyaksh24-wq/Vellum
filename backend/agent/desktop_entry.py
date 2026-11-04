"""Private child-process entry; separate from the importable lease owner."""
from agent.desktop_runtime import main

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--standalone", action="store_true", help="Run independently of the desktop parent pipe.")
    main(standalone=parser.parse_args().standalone)
