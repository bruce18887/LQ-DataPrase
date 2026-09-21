"""BFS 遍历、元数据过滤、预算与剪枝（spec §3.4）。

跑法：python manage.py test test.backend.test_sftp_search_walk
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp.search import contracts, walker  # noqa: E402
from test.backend.sftp_fake import FakeSession, FakeSftp, sample_tree  # noqa: E402


def walk(**over):
    over.setdefault('data_files_only', False)
    s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name', **over})
    sftp = FakeSftp(sample_tree())
    return walker.walk(s, FakeSession(sftp)), sftp


class FakeTreeSanityTests(SimpleTestCase):
    def test_root_lists_all_entries_including_hidden_dir(self):
        """钉**夹具**：FakeSftp 忠实模拟 SFTP 原始返回，`.` 开头条目照吐。

        跳过 dot 条目是 walker 的职责，由 HiddenAndBudgetTests 独立钉住——
        两件事分两个断言，任何一边退化都会红。
        """
        attrs = FakeSftp(sample_tree()).listdir_attr('/data')
        self.assertEqual([a.filename for a in attrs if _isdir(a)],
                         ['.hidden', 'backup', 'batch1', 'batch2'])
        self.assertEqual([a.filename for a in attrs if not _isdir(a)], [])


def _isdir(attr):
    import stat
    return stat.S_ISDIR(attr.st_mode)


class PruneTests(SimpleTestCase):
    def test_pruned_subtree_is_never_entered(self):
        _res, sftp = walk(prune_dirs=['backup'])
        self.assertNotIn('/data/backup', sftp.listdir_calls)

    def test_prune_matches_basename_only(self):
        _res, sftp = walk(prune_dirs=['batch*'])
        for called in sftp.listdir_calls:
            self.assertFalse(called.startswith('/data/batch'))

    def test_pruned_dirs_do_not_consume_entry_budget(self):
        """剪枝发生在进入前，否则「剪掉最外层」等于白剪。"""
        res, _ = walk(prune_dirs=['backup', 'batch1', 'batch2', '.hidden'],
                      max_entries=3)
        self.assertNotIn('truncated_entries', res.truncated)


class HiddenAndBudgetTests(SimpleTestCase):
    def test_dot_entries_skipped(self):
        res, _ = walk()
        self.assertFalse([c for c in res.candidates if '/.hidden/' in c.path])

    def test_dot_dir_not_entered(self):
        _res, sftp = walk()
        self.assertNotIn('/data/.hidden', sftp.listdir_calls)

    def test_entry_budget_reports_truncation(self):
        res, _ = walk(max_entries=2)
        self.assertIn('truncated_entries', res.truncated)

    def test_filtered_out_entries_still_consume_entry_budget(self):
        """spec §3.2 口径：预算数的是**遍历到的目录条目总数**，不是候选数。

        被 ``name_pattern`` 拒掉的 100 个文件必须照吃预算——否则「条目预算」退化成
        「候选上限的别名」，深树里海量不匹配文件就不受任何闸约束（§3.2「唯一真正防
        遍历失控的闸」）。挡在预算外的正是第二层的 ``/data/sub``：它没被剪枝、也不是
        dot 条目，唯一的解释是它前面的 101 个条目把 50 的预算吃光了。
        """
        tree = {'/data/sub/RT_target.csv': b'[DATA]\r\n'}
        for i in range(100):
            tree['/data/noise_%03d.txt' % i] = b'x'
        s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name',
                                  'name_pattern': '*RT*',
                                  'data_files_only': False, 'max_entries': 50})
        res = walker.walk(s, FakeSession(FakeSftp(tree)))
        self.assertIn('truncated_entries', res.truncated)
        self.assertNotIn('/data/sub/RT_target.csv',
                         {c.path for c in res.candidates})

    def test_candidate_budget_stops_listing(self):
        res, _ = walk(max_candidates=1)
        self.assertEqual(len(res.candidates), 1)
        self.assertIn('truncated_candidates', res.truncated)

    def test_expired_deadline_marks_cancelled(self):
        s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name',
                                  'data_files_only': False})
        res = walker.walk(s, FakeSession(FakeSftp(sample_tree())),
                          deadline=time.monotonic() - 1)
        self.assertTrue(res.cancelled)
        self.assertEqual(res.candidates, [])

    def test_cancel_event_stops_walk(self):
        ev = threading.Event()
        ev.set()
        res, _s = _walk_with_cancel(ev)
        self.assertTrue(res.cancelled)
        self.assertEqual(res.candidates, [])


def _walk_with_cancel(ev):
    s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name',
                              'data_files_only': False})
    sftp = FakeSftp(sample_tree())
    return walker.walk(s, FakeSession(sftp), cancel_event=ev), sftp


class DepthTests(SimpleTestCase):
    """``depth`` 档位到层数的映射口径：根 = 0 层，根的直属子目录 = 1 层。

    计划原文这两条断言与 ``contracts.DEPTH_TO_MAX``（``self``=0 / ``children``=1，已冻结）
    和前端文案「仅当前层 / 含下一层」互相矛盾，按口径修正、理由写在每条上：

    * ``test_self_excludes_nested`` 原本要求 ``self`` 档下 ``/data/batch1/RT_001.csv``
      **在**结果里，而同档的 ``test_self_only_lists_root`` 要求只列过 ``['/data']`` 一次——
      不列 batch1 就不可能看见它的文件，两条不可能同时成立。留 ``only_lists_root``
      （它才是「仅当前层」的定义），本条改成钉「self 连下一层都不给」。
    * ``test_custom_depth_honoured`` 原本用 ``max_depth=2`` 排除 ``batch1/Deep/RT_003.csv``，
      差一：``Deep`` 是 2 层目录，``max_depth=2`` 正好进得去。改成 1 排除 + 2 进入两条，
      把这个偏移本身钉住，免得日后谁再把它挪回去。
    """

    def test_self_only_lists_root(self):
        _res, sftp = walk(depth='self')
        self.assertEqual(sftp.listdir_calls, ['/data'])

    def test_self_excludes_nested(self):
        res, _ = walk(depth='self')
        self.assertNotIn('/data/batch1/Deep/RT_003.csv',
                         {c.path for c in res.candidates})
        self.assertNotIn('/data/batch1/RT_001.csv',
                         {c.path for c in res.candidates})

    def test_self_still_keeps_root_level_files(self):
        """上一条的正面：self 不是「什么都不给」，根目录自己的文件必须在。

        标准夹具的 /data 下没有直属文件，所以这里现造一棵有的树。
        """
        s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name',
                                  'depth': 'self', 'data_files_only': False})
        sftp = FakeSftp({'/data/top.csv': b'a,b\n',
                         '/data/batch1/RT_001.csv': b'[DATA]\r\n'})
        res = walker.walk(s, FakeSession(sftp))
        self.assertEqual({c.path for c in res.candidates}, {'/data/top.csv'})

    def test_children_includes_one_level_below(self):
        res, _ = walk(depth='children')
        paths = {c.path for c in res.candidates}
        self.assertIn('/data/batch1/RT_001.csv', paths)
        self.assertNotIn('/data/batch1/Deep/RT_003.csv', paths)

    def test_all_reaches_every_depth(self):
        res, _ = walk(depth='all')
        self.assertIn('/data/batch1/Deep/RT_003.csv',
                      {c.path for c in res.candidates})

    def test_custom_depth_one_excludes_second_level_dirs(self):
        res, sftp = walk(depth='custom', max_depth=1)
        paths = {c.path for c in res.candidates}
        self.assertIn('/data/batch1/RT_001.csv', paths)
        self.assertNotIn('/data/batch1/Deep/RT_003.csv', paths)
        self.assertNotIn('/data/batch1/Deep', sftp.listdir_calls)

    def test_custom_depth_two_enters_second_level_dirs(self):
        """偏移的另一半：max_depth 数的是目录层数，2 就该进 Deep。"""
        res, sftp = walk(depth='custom', max_depth=2)
        self.assertIn('/data/batch1/Deep/RT_003.csv',
                      {c.path for c in res.candidates})
        self.assertIn('/data/batch1/Deep', sftp.listdir_calls)

    def test_depth_truncation_reported(self):
        res, _ = walk(depth='children')
        self.assertIn('truncated_depth', res.truncated)

    def test_no_depth_truncation_when_all(self):
        res, _ = walk(depth='all')
        self.assertNotIn('truncated_depth', res.truncated)


class MetadataFilterTests(SimpleTestCase):
    def test_name_pattern_fnmatch(self):
        res, _ = walk(name_pattern='*RT*')
        self.assertTrue(res.candidates)
        self.assertTrue(all('RT_' in c.name for c in res.candidates))

    def test_min_size_excludes_everything_small(self):
        res, _ = walk(min_size=999_999)
        self.assertEqual(res.candidates, [])

    def test_modified_after_excludes_all(self):
        res, _ = walk(modified_after='2030-01-01')
        self.assertEqual(res.candidates, [])

    def test_modified_before_keeps_all(self):
        res, _ = walk(modified_before='2030-01-01')
        self.assertTrue(res.candidates)

    def test_mtime_missing_excludes_when_window_set(self):
        """时间窗存在但 mtime 拿不到时取排除，不把不确定的文件混进结果。"""
        self.assertFalse(walker.passes_metadata(
            'a.csv', 10, 0,
            contracts.parse_spec({'roots': ['/d'], 'mode': 'name',
                                  'modified_after': '2026-01-01'})))

    def test_data_files_only_drops_summary_and_non_csv(self):
        s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name'})
        res = walker.walk(s, FakeSession(FakeSftp(sample_tree())))
        names = {c.name for c in res.candidates}
        self.assertIn('RT_001.csv', names)
        self.assertNotIn('Sum_total.csv', names)
        self.assertNotIn('notes.txt', names)


class EventTests(SimpleTestCase):
    def test_unreadable_dir_emits_scoped_error_and_continues(self):
        """单目录读失败绝不能终止整次搜索（spec §3.4）。"""
        s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name',
                                  'data_files_only': False})
        sftp = FakeSftp(sample_tree(), unreadable=['/data/batch1'])
        res = walker.walk(s, FakeSession(sftp))
        self.assertIn(('dir', '/data/batch1'),
                      [(e['scope'], e['path']) for e in res.events
                       if e['kind'] == 'error'])
        self.assertTrue([c for c in res.candidates
                         if c.path.startswith('/data/batch2')])

    def test_on_candidate_streams_during_walk(self):
        """BFS 的存在理由：候选从一开始就在往外流，不是攒到最后一次性给。"""
        s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name',
                                  'data_files_only': False})
        seen = []
        walker.walk(s, FakeSession(FakeSftp(sample_tree())),
                    on_candidate=lambda c: seen.append(c.path))
        self.assertIn('/data/backup/RT_999.csv', seen)
        self.assertIn('/data/batch1/RT_001.csv', seen)

    def test_overlapping_roots_do_not_duplicate(self):
        s = contracts.parse_spec({'roots': ['/data', '/data/'],
                                  'mode': 'name', 'data_files_only': False})
        res = walker.walk(s, FakeSession(FakeSftp(sample_tree())))
        paths = [c.path for c in res.candidates]
        self.assertEqual(len(paths), len(set(paths)))


class SessionHygieneTests(SimpleTestCase):
    """借还平衡：walker 漏一次 give_back，搜索就会把 session 的连接借干。"""

    def _spec(self):
        return contracts.parse_spec({'roots': ['/data'], 'mode': 'name',
                                     'data_files_only': False})

    def test_every_borrow_is_given_back(self):
        session = FakeSession(FakeSftp(sample_tree()))
        walker.walk(self._spec(), session)
        self.assertEqual(session.borrow_count, session.give_back_count)
        self.assertTrue(session.borrow_count)

    def test_connection_level_failure_still_gives_back(self):
        """整条连接炸了（SFTPError）：每个目录成一条 error 事件、walk 不抛、连接归还。"""
        session = FakeSession(FakeSftp(sample_tree(), broken=True))
        res = walker.walk(self._spec(), session)
        self.assertEqual(session.borrow_count, session.give_back_count)
        self.assertEqual(res.candidates, [])
        self.assertTrue(res.events)
        self.assertTrue(all(e['kind'] == 'error' and e['scope'] == 'dir'
                            for e in res.events), res.events)
