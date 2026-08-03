"""SFTP-push the siyuan-lab repo to the VM (excludes secrets/.env). Idempotent.

Evidence dirs (exports/, backups/, workspace/, dbprobe/) are VM-runtime outputs:
they flow VM -> local via host/pull.py, never local -> VM. Pushing stale local
copies over freshly generated VM reports silently corrupts acceptance runs
(e.g. a pre-ADR-0006 negative_report.json clobbering the current one).
"""
import os, sys
sys.path.insert(0, r"C:/Users/georg/WorkBuddy/Siyuan/_refs")
import sshlib
import paramiko

LOCAL = r"C:/Users/georg/WorkBuddy/Siyuan/siyuan-lab"
REMOTE = "/opt/siyuan-lab"
# runtime/evidence dirs are excluded: they are generated ON the VM by the suite.
SKIP = {".git", "secrets", ".env", "__pycache__", "results",
        "exports", "backups", "workspace", "dbprobe"}

def walk(local, remote, sftp):
    for name in sorted(os.listdir(local)):
        if name in SKIP:
            continue
        lpath = os.path.join(local, name)
        rpath = remote + "/" + name
        if os.path.isdir(lpath):
            try:
                sftp.stat(rpath)
            except IOError:
                sftp.mkdir(rpath)
            walk(lpath, rpath, sftp)
        else:
            with open(lpath, "rb") as f:
                sftp.put(lpath, rpath)
            print("put", rpath)

def main():
    c = sshlib.connect()
    sftp = paramiko.SFTPClient.from_transport(c.get_transport())
    # ensure base dirs
    for d in ["compose", "scripts", "host", "corpus"]:
        try:
            sftp.stat(REMOTE + "/" + d)
        except IOError:
            sftp.mkdir(REMOTE + "/" + d)
    walk(LOCAL, REMOTE, sftp)
    # make scripts executable
    for root, dirs, files in os.walk(LOCAL):
        for f in files:
            if f.endswith(".sh"):
                rel = os.path.relpath(os.path.join(root, f), LOCAL).replace("\\", "/")
                try:
                    sftp.chmod(REMOTE + "/" + rel, 0o755)
                except Exception:
                    pass
    sftp.close()
    c.close()
    print("push complete")

if __name__ == "__main__":
    main()
