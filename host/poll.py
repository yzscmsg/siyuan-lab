#!/usr/bin/env python3
"""Poll the running S1 suite: prints whether it's alive and the tail of the log."""
import sys, time
sys.path.insert(0, r"C:/Users/georg/WorkBuddy/Siyuan/_refs")
import sshlib

LOG = "/opt/siyuan-lab/exports/s1_full.log"

def main():
    wait = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    lines = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    if wait:
        time.sleep(wait)
    running = sshlib.is_running("s1_acceptance.py")
    print("running:", running)
    out = sshlib.tail(LOG, lines)
    print(out)
    if not running:
        print("=== SUITE FINISHED ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
