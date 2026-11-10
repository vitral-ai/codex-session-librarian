"""Local Git CAS and lease prototype. Not proof of GitHub API behavior."""

import copy
import os
import subprocess
from .contracts import canonical


class Conflict(ValueError):
    pass


class GitControl:
    ref = "refs/heads/csl-backup-control-v1"

    def __init__(self, root):
        self.root = root
        self.env = {"PATH": os.environ["PATH"], "HOME": str(root),
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_AUTHOR_NAME": "CSL synthetic", "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
                    "GIT_COMMITTER_NAME": "CSL synthetic", "GIT_COMMITTER_EMAIL": "synthetic@example.invalid"}
        subprocess.run(["git", "init", "--bare", str(root)], check=True, capture_output=True, env=self.env)

    def git(self, *args, data=None, check=True):
        return subprocess.run(["git", "--git-dir", str(self.root), *args], input=data,
                              capture_output=True, env=self.env, check=check)

    def read(self):
        import json
        head = self.git("rev-parse", "--verify", self.ref, check=False)
        if head.returncode:
            return None, {"epoch": 0, "owner": "", "expires": 0, "latest": None, "intents": []}
        sha = head.stdout.decode().strip()
        return sha, json.loads(self.git("show", sha + ":control.json").stdout)

    def child(self, parent, state):
        blob = self.git("hash-object", "-w", "--stdin", data=canonical(state)).stdout.decode().strip()
        tree = self.git("mktree", data=f"100644 blob {blob}\tcontrol.json\n".encode()).stdout.decode().strip()
        args = ["commit-tree", tree] + (["-p", parent] if parent else [])
        return self.git(*args, data=b"synthetic F0 control\n").stdout.decode().strip()

    def advance(self, parent, state):
        child = self.child(parent, state)
        result = self.git("update-ref", self.ref, child, parent or "0" * 40, check=False)
        if result.returncode:
            raise Conflict("Control advanced; reread without losing other writers")
        return child

    def acquire(self, owner, now, ttl=600):
        parent, state = self.read()
        if state["owner"] and now < state["expires"]:
            raise Conflict("Lease occupied")
        state.update(epoch=state["epoch"] + 1, owner=owner, expires=now + ttl)
        return self.advance(parent, state), state["epoch"]

    def mutate(self, owner, epoch, now, *, checkpoint=None, renew=False):
        parent, state = self.read()
        if state["owner"] != owner or state["epoch"] != epoch or now >= state["expires"]:
            raise Conflict("Stale or expired lease")
        next_state = copy.deepcopy(state)
        if renew:
            next_state["expires"] = now + 600
        if checkpoint:
            next_state["latest"] = checkpoint
        return self.advance(parent, next_state)
