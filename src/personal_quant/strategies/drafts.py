"""Editable local drafts, independent of published strategy versions and accounts."""
import json
from pathlib import Path

from ..common import QuantError, digest, now_utc, write_json
from .spec import StrategySpec, ID


class DraftStore:
    def __init__(self, root):
        self.root = Path(root)

    def save(self, spec, *, expected_hash=None):
        spec = StrategySpec.from_dict(spec.export())
        body = spec.content()
        key = digest({"strategy_id": body["strategy_id"], "revision": body["revision"]})
        path = self.root / (key + ".json")
        from ..execution.daily import daily_lock
        with daily_lock(self.root / ".draft.lock"):
            if path.exists() and self.load(key)["hash"] != expected_hash:
                raise QuantError("STALE_DRAFT", "草稿已存在或被其他页面修改，请重新选择该草稿后编辑")
            value = {"schema_version": 1, "draft_id": key, "spec": spec.export(), "hash": digest(spec.export()), "saved_at": now_utc()}
            write_json(path, value)
        return value

    def load(self, key):
        if not isinstance(key, str) or not ID.fullmatch(key):
            raise QuantError("INVALID_DRAFT", "草稿标识非法")
        path = self.root / (key + ".json")
        value = json.loads(path.read_text())
        spec = StrategySpec.from_dict(value["spec"])
        expected_key = digest({"strategy_id": spec.content()["strategy_id"], "revision": spec.content()["revision"]})
        if value.get("schema_version") != 1 or value["hash"] != digest(spec.export()) or key != expected_key or value.get("draft_id") != key:
            raise QuantError("INVALID_DRAFT", "草稿文件与指纹不一致")
        return value

    def list(self):
        return {file.stem: self.load(file.stem) for file in sorted(self.root.glob("*.json"))} if self.root.exists() else {}


def differences(before, after):
    result = []
    def visit(first, second, prefix=""):
        if isinstance(first, dict) and isinstance(second, dict):
            for key in sorted(first.keys() | second.keys()):
                visit(first.get(key), second.get(key), prefix + ("." if prefix else "") + key)
        elif first != second:
            result.append({"字段": prefix, "原值": str(first), "新值": str(second)})
    visit(before, after)
    return result
