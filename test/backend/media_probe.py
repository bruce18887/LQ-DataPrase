# test/backend/media_probe.py
"""「端点没往 MEDIA_ROOT 写东西」的探测器 + 它的对照组 —— weight 两个测试模块共用。

为什么单独成文件（Task 5 修复轮 R6）：`_media_paths()` 在 `test_weight_api.py` 与
`test_weight_export_api.py` 各写了一份，**探测器一旦有副本就有人只改一份** ⇒ 「请求前后
集合相等」那条断言会各红各的、甚至一起失效。仓内 `excel_cf.py` / `sftp_fake.py` 已是同一
形态：共用逻辑放非 `test_` 前缀的助手模块，Django 发现器（pattern `test*.py`）不会把它
当成用例文件，只有显式 `from test.backend.media_probe import …` 才加载。

`media_paths()` 在目录不存在时返回**空集**（不是 None、不抛）：新检出 / 新 slot 的
MEDIA_ROOT 可以还没建，空集才是「现在一个文件都没有」这个真值。
"""
from pathlib import Path

from django.conf import settings


def media_paths() -> frozenset[str]:
    """MEDIA_ROOT 下所有文件的绝对路径集合（目录不存在＝空集，不是「探测器坏了」）。"""
    root = Path(settings.MEDIA_ROOT)
    if not root.exists():
        return frozenset()
    return frozenset(str(p) for p in root.rglob('*') if p.is_file())


class MediaProbeControlMixin:
    """对照组：混入它的类里那条「前后 `media_paths()` 相等」必须**不是**恒真。

    没有对照组的「什么都没发生」断言是可以恒真的（探测器写成 `return frozenset()` 也全绿），
    所以每条用它承诺「零落盘」的通路都要混入本 mixin —— 各自都有一份能报得出新增文件的
    哨兵。（`test_weight_api.py` 的 parse 侧以前只有那一份对照组，导出侧那条没有 ⇒ 只在该
    模块被选中时才跟着红的对照组，affected 档根本带不到它。）

    哨兵写在 `settings.MEDIA_ROOT` 下（`manage.py test` 走 `config.settings.unit` ⇒
    `test/unit-data/media`，被 gitignore），`finally` 里删掉 ⇒ 不留 scratch。
    """

    def test_media_probe_actually_detects_a_new_file(self):
        root = Path(settings.MEDIA_ROOT)
        root.mkdir(parents=True, exist_ok=True)
        sentinel = root / 'weight-probe-control.txt'
        before = media_paths()
        try:
            sentinel.write_text('control', encoding='utf-8')
            self.assertNotIn(str(sentinel), before)
            self.assertIn(str(sentinel), media_paths())
        finally:
            sentinel.unlink(missing_ok=True)
        self.assertEqual(media_paths(), before)
