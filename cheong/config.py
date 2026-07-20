"""설정 로딩 및 값 참조 유틸."""
from pathlib import Path

import yaml


def load_config(path="config.yaml"):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"설정 파일이 없습니다: {path}\n"
            "  → config.example.yaml 를 config.yaml 로 복사한 뒤 값을 채우세요."
        )
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_value(spec, config):
    """'profile.name' 같은 점 표기를 config['profile']['name'] 로 해석."""
    cur = config
    for key in spec.split("."):
        cur = cur[key]
    return cur


def get_target(config, name):
    for t in config.get("targets", []):
        if t.get("name") == name:
            return t
    names = [t.get("name") for t in config.get("targets", [])]
    raise KeyError(f"타겟 '{name}' 을 찾을 수 없습니다. 사용 가능: {names}")
