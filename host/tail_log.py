import sys
sys.path.insert(0, r"C:/Users/georg/WorkBuddy/Siyuan/_refs")
import sshlib

LOG = sys.argv[1] if len(sys.argv) > 1 else "/opt/siyuan-lab/exports/s1_restore_only.log"
lines = int(sys.argv[2]) if len(sys.argv) > 2 else 40

out = sshlib.tail(LOG, lines)
print(out)
