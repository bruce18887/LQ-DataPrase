"""测试脚手架：给「所有消费 ``_load_df_from_request`` 的视图模块」统一打桩。

``apps/analysis/views`` 按 600 行上限拆成多个 mixin 模块后，每个模块各持有一份该
函数的独立绑定（lessons R6③：monkey-patch 必须打在**实际消费模块**上）。逐个硬写
模块名会在每次拆分时漏掉新模块——拆出 ``param_actions`` 后有 25 条用例打到真实
loader 变成 500。所以这里在打桩时扫描 views 包，按「实际绑定了该名字」动态收集，
调用方不需要再维护模块清单。
"""

import importlib
import pkgutil
import types


def loader_consumers():
    """返回 ``apps.analysis.views`` 下绑定了 ``_load_df_from_request`` 的模块。"""
    from apps.analysis import views as views_pkg

    modules = []
    for info in pkgutil.iter_modules(views_pkg.__path__):
        if info.name.startswith('_'):
            continue
        module = importlib.import_module(f'{views_pkg.__name__}.{info.name}')
        if getattr(module, '_load_df_from_request', None) is not None:
            modules.append(module)
    if not modules:
        raise AssertionError('未找到任何消费 _load_df_from_request 的视图模块')
    return modules


def patch_df_loader(df, datafile, metadata):
    """把 df/datafile/metadata 喂给所有消费模块，返回一个无参 restore 回调。"""
    def fake_load(request):
        return df, datafile, metadata, None

    originals = [(module, module._load_df_from_request)
                 for module in loader_consumers()]
    for module, _ in originals:
        module._load_df_from_request = fake_load

    def restore():
        for module, original in originals:
            module._load_df_from_request = original

    return restore


def fake_datafile(**overrides):
    """视图只读 id/filename/format_type（lessons R6②：字段要给全）。"""
    fields = {'id': 1, 'filename': 'fake.csv', 'format_type': 'CTA8290D'}
    fields.update(overrides)
    return types.SimpleNamespace(**fields)
