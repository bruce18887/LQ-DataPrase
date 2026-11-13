"""介绍书（/intro/）serving 与标签页图标（favicon）路由的 T1 契约。

为什么这批断言必须是后端契约而不是 e2e（Task 11 根因链，设计稿 §3.2）：

* ``docs/intro/.vitepress/config.mts`` 过去没有 ``head`` 数组 ⇒ 构建产物里根本没有
  ``<link rel="icon">`` ⇒ 浏览器无条件退回请求 ``/favicon.ico``，而 ``config/urls.py``
  只挂了 ``/favicon.svg`` ⇒ 那个请求落进 ``config/urls.py`` 末尾的 SPA catch-all，
  拿到 **200 + ``text/html`` 的 SPA 壳**（实测：不是 404）⇒ 图标解不出来，标签页空白。
* 这个失败在既有自动化里**看不见**：e2e 的 console 采集把 favicon 当噪声整体过滤
  （``frontend/e2e/helpers/nav.ts:30`` 的 ``/favicon|.../``），判据抓不到 ≠ 没问题，
  只有人工走读会撞见 ⇒ 用 T1 把 HTML 声明与两条路由钉死。

serving 形态说明：Django 只在 standalone/server 档把 ``frontend/dist`` 注册进
``TEMPLATES[0]['DIRS']``（``_frontend_dist()`` 读的就是它），所以本测试用临时目录
复刻该形态；但 ① 的 ``intro/index.html`` 取**真实 VitePress 构建产物**
（``docs/intro/.vitepress/dist/index.html``）——牙在这里：改 ``config.mts`` 后不重跑
``npm run intro:build``，这条就红。**只有 ① 读产物**，所以 skip 也只挂在 ① 上
（产物缺失 = 未构建 ≠ 回归）；②③ 两条 favicon 路由契约不碰产物、**恒跑** ——
CI 的 backend job 不跑 ``npm run build``（``.github/workflows/ci.yml``），
类级 skip 会把那两条一起跳掉，新加的 ``/favicon.ico`` 路由在 CI 上就成了零守卫。

运行：``python manage.py test test.backend.test_intro_serving``
（``manage.py test`` 默认走 ``config.settings.unit``，见 manage.py 的 default_settings_module。）
"""
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import Client, SimpleTestCase, override_settings

REPO = Path(__file__).resolve().parents[2]
INTRO_DIST = REPO / 'docs' / 'intro' / '.vitepress' / 'dist'
INTRO_INDEX = INTRO_DIST / 'index.html'
PUBLIC_FAVICON_SVG = REPO / 'frontend' / 'public' / 'favicon.svg'

# SPA 壳占位：真实 frontend_dist 根下一定有 index.html（catch-all 的模板）。
# 复刻它的目的：修复前 /favicon.ico 落 catch-all 会返回 **200 + text/html 的 SPA 壳**，
# 只断状态码会假绿——浏览器拿到 HTML 当图标必然失败。所以断言抓 Content-Type 与字节。
SPA_SHELL = '<!doctype html><html><body>SPA shell fixture</body></html>'


class IntroFaviconTests(SimpleTestCase):
    """GET /intro/ 的 HTML 声明 + /favicon.ico 与 /favicon.svg 两条路由的契约。"""

    def setUp(self):
        self.dist = Path(tempfile.mkdtemp(prefix='t11-intro-dist-'))
        self.addCleanup(shutil.rmtree, self.dist, ignore_errors=True)
        (self.dist / 'intro').mkdir()
        # 三条共用的 serving 舞台（临时 dist，避免污染真实前端产物）：favicon.svg 与
        # SPA 壳——两条 favicon 路由契约只依赖这两样，不依赖介绍书产物。
        shutil.copyfile(PUBLIC_FAVICON_SVG, self.dist / 'favicon.svg')
        (self.dist / 'index.html').write_text(SPA_SHELL, encoding='utf-8')

        templates = [dict(settings.TEMPLATES[0])]
        templates[0]['DIRS'] = [str(self.dist)]
        self._override = override_settings(TEMPLATES=templates)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.client = Client()

    @staticmethod
    def _body(resp) -> bytes:
        """FileResponse 是流式响应，没有 `.content`（读它会 AttributeError）。"""
        if hasattr(resp, 'streaming_content'):
            return b''.join(resp.streaming_content)
        return resp.content

    def test_intro_page_declares_svg_tab_icon(self):
        """① /intro/ 返回的 HTML 必须同时含 rel="icon" 与 /favicon.svg。

        根因：config.mts 过去没有 head ⇒ 产物里没这条 ⇒ 浏览器退回 /favicon.ico，
        而那个请求落 catch-all 拿到的是 200 + text/html 的 SPA 壳（图标解不出来）。
        href 必须是**绝对根路径** /favicon.svg：介绍书 base 是 /intro/，相对路径会解析成
        /intro/favicon.svg，而 Django 只在根路径挂该文件。
        """
        if not INTRO_INDEX.is_file():
            self.skipTest(
                '介绍书构建产物缺失（docs/intro/.vitepress/dist/index.html）——本条断的是产物里的 '
                'link 声明，先跑 npm run intro:build（根 npm run build 会自动链）；'
                '②③ 两条 favicon 路由契约不依赖产物，不受影响'
            )
        shutil.copyfile(INTRO_INDEX, self.dist / 'intro' / 'index.html')
        resp = self.client.get('/intro/')
        self.assertEqual(resp.status_code, 200)
        html = self._body(resp).decode('utf-8')
        self.assertIn('rel="icon"', html, '介绍书 HTML 缺少标签页图标声明（config.mts head 被删了？）')
        self.assertIn('/favicon.svg', html)

    def test_favicon_ico_serves_svg_bytes_not_spa_shell(self):
        """② GET /favicon.ico 必须 200 且真的是那份 SVG。

        浏览器对 /favicon.ico 的兜底请求是无条件的（且历史书签/部分代理会直接要这个路径）。
        web 根下没有 .ico 资产——打包期 build/icon.ico 只给 Windows 外壳用——所以路由复用
        favicon.svg。**返回可用的 SVG 而不是落进 catch-all 那份 200 + text/html 的 SPA 壳
        才是这条路由的目的**（修复前实测就是这个形状，并非 404）。
        Content-Type 实测钉死：FileResponse 按**文件名**（favicon.svg）猜 MIME，
        本机实测（Python mimetypes.guess_type 与本页断言双重验证）为 image/svg+xml，
        与 URL 后缀 .ico 无关；现代 Chromium/Firefox 按内容识别，接受该 MIME。
        """
        resp = self.client.get('/favicon.ico')
        # 这条**不足以**抓到根因：落进 catch-all 时状态码同样是 200，真正咬住的是下面
        # 两条 MIME 与字节。留它的目的是挡另一种失效（路由被摘到 404 / dist 未配置）。
        self.assertEqual(resp.status_code, 200, 'favicon.ico 非 200（路由被摘或 frontend_dist 未配置）')
        self.assertEqual(resp.headers['Content-Type'], 'image/svg+xml')
        self.assertEqual(self._body(resp), PUBLIC_FAVICON_SVG.read_bytes())

    def test_favicon_svg_route_still_served(self):
        """③ 既有的 /favicon.svg（SPA index.html 引用）不能被新路由挤掉。"""
        resp = self.client.get('/favicon.svg')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['Content-Type'], 'image/svg+xml')
        self.assertEqual(self._body(resp), PUBLIC_FAVICON_SVG.read_bytes())
