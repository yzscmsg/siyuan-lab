"""Pull S1 evidence (exports/, backups manifests) from the VM into the local repo.
Reverse of push.py. Writes to siyuan-lab/results/."""
import os, sys
sys.path.insert(0, r"C:/Users/georg/WorkBuddy/Siyuan/_refs")
import sshlib
import paramiko

REMOTE = "/opt/siyuan-lab/exports"
LOCAL = r"C:/Users/georg/WorkBuddy/Siyuan/siyuan-lab/results/exports"

def main():
    c = sshlib.connect()
    sftp = paramiko.SFTPClient.from_transport(c.get_transport())
    os.makedirs(LOCAL, exist_ok=True)
    # pull entire exports tree
    def walk(rpath, lpath):
        for name in sorted(sftp.listdir(rpath)):
            rp = rpath + "/" + name
            lp = os.path.join(lpath, name)
            try:
                sftp.stat(rp + "/")
                os.makedirs(lp, exist_ok=True)
                walk(rp, lp)
            except IOError:
                sftp.get(rp, lp)
                print("get", rp)
    walk(REMOTE, LOCAL)
    sftp.close(); c.close()
    print("pull complete ->", LOCAL)

if __name__ == "__main__":
    main()
