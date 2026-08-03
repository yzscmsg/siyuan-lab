"""Poll a detached VM job's log once and report whether it is still running.

Designed for short, repeated calls from the operator workstation: the shell
harness here kills any foreground command that runs for minutes, so a long
"tail -f" style follower is not an option. One call = one snapshot.

    python host/follow.py                       # last 60 lines of s1_full.log
    python host/follow.py --lines 200
    python host/follow.py --log /opt/siyuan-lab/exports/reseed.log --pattern seed.py
"""
import argparse
import sys

sys.path.insert(0, r"C:/Users/georg/WorkBuddy/Siyuan/_refs")
import sshlib  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="/opt/siyuan-lab/exports/s1_full.log")
    ap.add_argument("--pattern", default="s1_acceptance.py")
    ap.add_argument("--lines", type=int, default=60)
    a = ap.parse_args()

    running = sshlib.is_running(a.pattern)
    text = sshlib.tail(a.log, a.lines)
    print(text.rstrip())
    print("\n[follow] %s -> %s" % (a.pattern, "RUNNING" if running else "finished"))
    return 0 if not running else 3


if __name__ == "__main__":
    sys.exit(main())
