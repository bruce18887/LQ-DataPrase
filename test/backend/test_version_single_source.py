"""版本号为单一事实源的护栏（架构评审 P1-10 连带项）。

`docs/reference/version-management.md` 声明版本**只**定义在 `frontend/package.json`，
但 P0-5 新增的 `pyproject.toml` 又落了第二份 `version`。两份数字必然漂移（本次评审就抓到
文档停在 0.2.0 而实际已是 0.7.0），所以要么由工具动态读取，要么由用例钉住两者一致。
本项目不 `pip install .`（见 pyproject 顶部说明），`version` 只是元数据 —— 取「加护栏」
而不是「改动态」。
"""
import json
import re
import tomllib
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]

# 「当前 x.y.z」形态即算把版本写进了文档；示例里的 0.x.y / v0.1.0 → v0.2.0 不算
_PINNED_CURRENT = re.compile(r'当前\s*`?\d+\.\d+\.\d+')


class VersionSingleSourceTests(SimpleTestCase):
    """pyproject 与 frontend/package.json 的版本必须一致，文档不得复述当前值。"""

    def _package_json_version(self):
        text = (ROOT / 'frontend' / 'package.json').read_text(encoding='utf-8')
        return json.loads(text)['version']

    def _pyproject_version(self):
        data = tomllib.loads((ROOT / 'pyproject.toml').read_bytes().decode('utf-8'))
        return data['project']['version']

    def test_pyproject_matches_package_json(self):
        npm_version = self._package_json_version()
        self.assertEqual(
            self._pyproject_version(), npm_version,
            'pyproject.toml 的 [project].version 必须与 frontend/package.json 的 version '
            '同步（发版只改 package.json，见 docs/reference/version-management.md）')

    def test_version_spec_doc_does_not_pin_the_current_version(self):
        text = (ROOT / 'docs' / 'reference' / 'version-management.md').read_text(
            encoding='utf-8')
        offenders = [line.strip() for line in text.splitlines()
                     if _PINNED_CURRENT.search(line)]
        self.assertEqual(
            offenders, [],
            'version-management.md 里写死了当前版本号——它每次发版都会过期')
