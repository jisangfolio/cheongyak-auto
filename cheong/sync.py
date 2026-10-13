"""state/state.json 을 커밋·push 한다 (GitHub Actions 와 Mac 이 같이 쓴다).

  python -m cheong.sync "커밋 메시지"

두 곳이 거의 동시에 push 해서 state.json 이 충돌하면, 양쪽 기록을 합쳐(합집합) 다시 올린다.
state.json 말고 다른 파일이 충돌하면 손대지 않고 멈춘다.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REL = "state/state.json"


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "GIT_EDITOR": "true"})
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)} 실패: {r.stderr.strip() or r.stdout.strip()}")
    return r


def union(a, b):
    """두 state 를 합친다: 처음 본 날짜는 더 이른 것, 리마인더는 둘 다, 0건 카운터는 큰 쪽."""
    seen = dict(b.get("seen", {}))
    for k, d in a.get("seen", {}).items():
        seen[k] = min(d, seen.get(k, d))
    reminded = {}
    for src in (b.get("reminded", {}), a.get("reminded", {})):
        for k, v in src.items():
            reminded[k] = sorted(set(reminded.get(k, [])) | set(v))
    zero = dict(b.get("zero", {}))
    for k, v in a.get("zero", {}).items():
        zero[k] = max(v, zero.get(k, 0))
    return {"initialized": bool(a.get("initialized") or b.get("initialized")), "zero": zero,
            "seen": dict(sorted(seen.items())), "reminded": reminded}


def _stage(n):
    r = git("show", f":{n}:{REL}", check=False)
    return json.loads(r.stdout or "{}") if r.returncode == 0 else {}


def main(msg):
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    git("add", REL)
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        print("[sync] 바뀐 상태 없음")
        return
    git("commit", "-q", "-m", msg)
    for attempt in range(1, 4):
        if git("push", "origin", branch, check=False).returncode == 0:
            print(f"[sync] push 완료 ({branch})")
            return
        print(f"[sync] push 거절 → 원격과 합치기 ({attempt}/3)")
        git("fetch", "-q", "origin", branch)
        if git("rebase", "--autostash", f"origin/{branch}", check=False).returncode:
            conflicted = git("diff", "--name-only", "--diff-filter=U").stdout.split()
            if conflicted != [REL]:
                git("rebase", "--abort", check=False)
                raise SystemExit(f"[sync] state.json 외 충돌: {conflicted} — 직접 확인 필요")
            merged = union(_stage(3), _stage(2))      # 3=내 커밋, 2=원격
            (ROOT / REL).write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
            git("add", REL)
            git("rebase", "--continue")
    raise SystemExit("[sync] push 3번 실패")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "state: update")
