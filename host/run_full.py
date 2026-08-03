"""Launch the S1 acceptance suite DETACHED on the VM and follow its log.

The full run swaps container images and restores into a fresh instance; it
outlives a normal SSH channel. Killing the channel mid-stage would leave the
lab half-upgraded, so the job is detached with setsid and polled instead.

    python host/run_full.py             # --full --yes
    python host/run_full.py --stages safe
"""
import sys
import time

sys.path.insert(0, r"C:/Users/georg/WorkBuddy/Siyuan/_refs")
import sshlib  # noqa: E402

BASE = "/opt/siyuan-lab"
LOG = BASE + "/exports/s1_full.log"
PATTERN = "s1_acceptance.py"


def main():
    args = " ".join(sys.argv[1:]) or "--full --yes"
    if sshlib.is_running(PATTERN):
        print("a run is already in progress; following it instead")
    else:
        sshlib.run("rm -f %s" % LOG, quiet=True)
        sshlib.run_detached("cd %s && python3 -u scripts/s1_acceptance.py %s"
                            % (BASE, args), LOG)
        print("launched: s1_acceptance.py %s" % args)

    seen = 0
    idle = 0
    while True:
        text = sshlib.tail(LOG, 4000)
        if len(text) > seen:
            sys.stdout.write(text[seen:])
            sys.stdout.flush()
            seen = len(text)
            idle = 0
        else:
            idle += 1
        if not sshlib.is_running(PATTERN):
            # one last drain, then stop
            text = sshlib.tail(LOG, 4000)
            if len(text) > seen:
                sys.stdout.write(text[seen:])
            print("\n[run_full] finished")
            return 0
        if idle > 240:  # 20 min with no new output
            print("\n[run_full] no output for 20 min; still running - detaching")
            return 2
        time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
