"""T1: analysis loaders reuse authorized rows without changing their contracts."""

import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import pandas as pd
from django.contrib.auth import get_user_model
from django.db import OperationalError, connection
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.analysis.views import AnalysisViewSet, _helpers
from apps.datafiles import services
from apps.datafiles.models import DataFile


class AnalysisLoadDbCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='a3_loader_owner')
        cls.other_user = get_user_model().objects.create_user(username='a3_loader_other')

    def setUp(self):
        folder = TemporaryDirectory(prefix='a3-loader-')
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.factory = APIRequestFactory()
        self.payloads = {}
        self.files = [self.make_file(i, self.user) for i in range(1, 4)]
        self.foreign = self.make_file(4, self.other_user)
        self.absent_id = self.foreign.pk + 1000
        services._parse_cache.clear()
        self.addCleanup(services._parse_cache.clear)
        # Keep the real service wrapper, path checks, cache and ORM. Only the
        # parser is replaced, so a forgotten third argument adds a real SELECT.
        self.parser = Mock()
        self.parser.parse.side_effect = lambda path: self.payloads[path]
        parser_patch = patch.object(services, 'get_parser', return_value=self.parser)
        parser_patch.start()
        self.addCleanup(parser_patch.stop)

    def make_file(self, index, owner):
        path = self.folder / f'lot-{index}.csv'
        path.write_text(f'P1\n{index}\n{index + 1}\n', encoding='utf-8')
        frame = pd.DataFrame({'P1': [float(index), float(index + 1)]})
        metadata = {
            'format': 'CTA8290D', 'lot': f'LOT-{index}',
            'mins': {'P1': str(index - 1)}, 'maxs': {'P1': str(index + 2)},
            'units': {'P1': 'mV'},
        }
        self.payloads[str(path)] = (frame, metadata)
        return DataFile.objects.create(
            owner=owner, filename=path.name, file_path=str(path),
            file_size=path.stat().st_size, format_type='CTA8290D',
            metadata={'database_only': index},
        )

    def raw_request(self, payload=None, *, query=False, url=None):
        url = url or '/api/v1/analysis/histogram/'
        payload = {} if payload is None else payload
        if query:
            request = self.factory.get(url, payload)
        else:
            request = self.factory.post(url, payload, format='json')
        force_authenticate(request, user=self.user)
        return request

    def request(self, payload=None, **kwargs):
        request = APIView().initialize_request(self.raw_request(payload, **kwargs))
        self.assertIs(request.user, self.user)
        return request

    def assert_single_loaded(self, result, datafile):
        self.assertEqual(len(result), 4)
        frame, loaded_file, metadata, error = result
        expected_frame, expected_metadata = self.payloads[datafile.file_path]
        self.assertIsNone(error)
        self.assertEqual(loaded_file, datafile)
        self.assertIs(frame, expected_frame)
        self.assertEqual(metadata['lot'], expected_metadata['lot'])
        self.assertEqual(metadata['mins'], expected_metadata['mins'])
        self.assertNotIn('database_only', metadata)

    def test_single_body_contract_preserves_frame_and_metadata_inputs(self):
        datafile = self.files[0]
        frame, metadata = self.payloads[datafile.file_path]
        original_frame, original_metadata = frame.copy(deep=True), deepcopy(metadata)
        request = self.request({'file_id': str(datafile.pk), 'params': ['P1']})
        original_data = deepcopy(request.data)
        result = _helpers._load_df_from_request(request)
        self.assert_single_loaded(result, datafile)
        pd.testing.assert_frame_equal(frame, original_frame)
        self.assertEqual(metadata, original_metadata)
        self.assertEqual(request.data, original_data)

    def test_single_query_contract(self):
        datafile = self.files[1]
        request = self.request({'file_id': str(datafile.pk)}, query=True)
        original_query = request.query_params.copy()
        self.assert_single_loaded(_helpers._load_df_from_request(request), datafile)
        self.assertEqual(request.query_params, original_query)

    def test_single_body_id_takes_precedence_over_query(self):
        request = self.request(
            {'file_id': self.files[0].pk},
            url=f'/api/v1/analysis/histogram/?file_id={self.files[1].pk}',
        )
        self.assert_single_loaded(_helpers._load_df_from_request(request), self.files[0])

    def test_single_empty_body_id_falls_back_to_query(self):
        request = self.request(
            {'file_id': ''},
            url=f'/api/v1/analysis/histogram/?file_id={self.files[1].pk}',
        )
        self.assert_single_loaded(_helpers._load_df_from_request(request), self.files[1])

    def test_single_uses_one_select_on_cold_and_warm_cache(self):
        for query in (False, True):
            with self.subTest(query=query):
                request = self.request({'file_id': self.files[0].pk}, query=query)
                with self.assertNumQueries(1):
                    result = _helpers._load_df_from_request(request)
                self.assert_single_loaded(result, self.files[0])
        self.assertEqual(self.parser.parse.call_count, 1)

    def test_single_passes_the_authorized_row_to_cache_wrapper(self):
        with patch.object(
            _helpers, 'get_cached_parsed_file', wraps=services.get_cached_parsed_file,
        ) as wrapper:
            result = _helpers._load_df_from_request(
                self.request({'file_id': self.files[0].pk}),
            )
        self.assert_single_loaded(result, self.files[0])
        wrapper.assert_called_once_with(self.files[0].pk, self.user.pk, result[1])

    def test_single_missing_id_never_queries_or_calls_wrapper(self):
        for payload in ({}, {'file_id': None}, {'file_id': ''}, {'file_id': 0}):
            with self.subTest(payload=payload), patch.object(
                _helpers, 'get_cached_parsed_file', wraps=services.get_cached_parsed_file,
            ) as wrapper:
                with self.assertNumQueries(0):
                    result = _helpers._load_df_from_request(self.request(payload))
                self.assertEqual(result, (None, None, None, 'file_id_required'))
                wrapper.assert_not_called()

    def test_single_invalid_id_never_queries_or_calls_wrapper(self):
        for file_id in ('abc', '1.5', ['1'], {'id': 1}):
            with self.subTest(file_id=file_id), patch.object(
                _helpers, 'get_cached_parsed_file', wraps=services.get_cached_parsed_file,
            ) as wrapper:
                with self.assertNumQueries(0):
                    result = _helpers._load_df_from_request(self.request({'file_id': file_id}))
                self.assertEqual(result, (None, None, None, 'file_id_invalid'))
                wrapper.assert_not_called()

    def test_single_foreign_and_absent_ids_keep_not_found_contract(self):
        for file_id in (self.foreign.pk, self.absent_id):
            with self.subTest(file_id=file_id), self.assertNumQueries(1):
                result = _helpers._load_df_from_request(self.request({'file_id': file_id}))
                self.assertEqual(result, (None, None, None, 'file_not_found'))
        self.parser.parse.assert_not_called()

    def test_single_foreign_id_does_not_call_cache_wrapper(self):
        with patch.object(
            _helpers, 'get_cached_parsed_file', wraps=services.get_cached_parsed_file,
        ) as wrapper:
            result = _helpers._load_df_from_request(self.request({'file_id': self.foreign.pk}))
        self.assertEqual(result, (None, None, None, 'file_not_found'))
        self.parser.parse.assert_not_called()
        wrapper.assert_not_called()

    def test_single_absent_id_does_not_call_cache_wrapper(self):
        with patch.object(
            _helpers, 'get_cached_parsed_file', wraps=services.get_cached_parsed_file,
        ) as wrapper:
            result = _helpers._load_df_from_request(self.request({'file_id': self.absent_id}))
        self.assertEqual(result, (None, None, None, 'file_not_found'))
        self.parser.parse.assert_not_called()
        wrapper.assert_not_called()

    def test_single_missing_disk_keeps_parse_failed_code(self):
        datafile = self.files[0]
        Path(datafile.file_path).unlink()
        with self.assertNumQueries(1):
            result = _helpers._load_df_from_request(self.request({'file_id': datafile.pk}))
        self.assertEqual(result, (None, None, None, 'file_not_found_or_parse_failed'))
        self.parser.parse.assert_not_called()

    def test_single_parser_none_keeps_parse_failed_code(self):
        self.parser.parse.side_effect = None
        self.parser.parse.return_value = (None, {'parse_error': 'fixture'})
        with self.assertNumQueries(1):
            result = _helpers._load_df_from_request(self.request({'file_id': self.files[0].pk}))
        self.assertEqual(result, (None, None, None, 'file_not_found_or_parse_failed'))

    def test_single_parser_exception_keeps_not_found_code(self):
        self.parser.parse.side_effect = ValueError('synthetic parser failure')
        with self.assertLogs('apps.datafiles.services', level='WARNING'), self.assertNumQueries(1):
            result = _helpers._load_df_from_request(self.request({'file_id': self.files[0].pk}))
        self.assertEqual(result, (None, None, None, 'file_not_found'))

    def test_single_duplicate_columns_keep_first_without_mutating_cached_frame(self):
        datafile = self.files[0]
        frame = pd.DataFrame([[1., 90., 3.], [2., 80., 4.]], columns=['P1', 'P1', 'P2'])
        metadata = self.payloads[datafile.file_path][1]
        self.payloads[datafile.file_path] = (frame, metadata)
        original_frame, original_metadata = frame.copy(deep=True), deepcopy(metadata)
        result = _helpers._load_df_from_request(self.request({'file_id': datafile.pk}))
        pd.testing.assert_frame_equal(result[0], frame.iloc[:, [0, 2]])
        self.assertIsNot(result[0], frame)
        pd.testing.assert_frame_equal(frame, original_frame)
        self.assertEqual(metadata, original_metadata)
        self.assertEqual(result[1], datafile)
        self.assertIsNone(result[3])

    def test_multiple_uses_one_select_for_one_or_n_files_cold_and_warm(self):
        for count in (1, 3):
            services._parse_cache.clear()
            self.parser.parse.reset_mock()
            ids = [file.pk for file in self.files[:count]]
            for warm in (False, True):
                with self.subTest(count=count, warm=warm), self.assertNumQueries(1):
                    loaded = _helpers._load_files_from_request(self.request(), ids)
                    self.assertEqual([entry['file_id'] for entry in loaded], ids)
            self.assertEqual(self.parser.parse.call_count, count)

    def test_multiple_order_duplicates_shape_and_distinct_metadata_are_preserved(self):
        expected = [self.files[1], self.files[0], self.files[1], self.files[2]]
        ids = [str(file.pk) for file in expected]
        original_ids = ids.copy()
        original_payloads = {
            path: (frame.copy(deep=True), deepcopy(metadata))
            for path, (frame, metadata) in self.payloads.items()
        }
        request = self.request({'file_ids': ids, 'params': ['P1']})
        original_data = deepcopy(request.data)
        loaded = _helpers._load_files_from_request(request, ids)
        self.assertEqual([entry['file_id'] for entry in loaded], [file.pk for file in expected])
        for entry, datafile in zip(loaded, expected):
            self.assertEqual(set(entry), {'df', 'metadata', 'file_id', 'filename', 'timestamp'})
            self.assertIs(entry['df'], self.payloads[datafile.file_path][0])
            self.assertEqual(entry['metadata']['lot'], self.payloads[datafile.file_path][1]['lot'])
            self.assertEqual(entry['filename'], datafile.filename)
            self.assertEqual(entry['timestamp'], datafile.created_at.strftime('%Y-%m-%d %H:%M:%S'))
        self.assertIs(loaded[0]['df'], loaded[2]['df'])
        self.assertIsNot(loaded[0], loaded[2])
        self.assertIsNot(loaded[0]['metadata'], loaded[1]['metadata'])
        self.assertIsNot(loaded[1]['metadata'], loaded[3]['metadata'])
        self.assertEqual(ids, original_ids)
        self.assertEqual(request.data, original_data)
        for path, (frame, metadata) in self.payloads.items():
            pd.testing.assert_frame_equal(frame, original_payloads[path][0])
            self.assertEqual(metadata, original_payloads[path][1])

    def test_multiple_mixed_invalid_absent_and_foreign_ids_are_silently_skipped(self):
        ids = ['bad', self.absent_id, str(self.files[1].pk), None, {}, [],
               self.foreign.pk, '1.5', float('inf'), float('nan'), self.files[0].pk]
        with patch.object(
            _helpers, 'get_cached_parsed_file', wraps=services.get_cached_parsed_file,
        ) as wrapper:
            loaded = _helpers._load_files_from_request(self.request(), ids)
        expected_ids = [self.files[1].pk, self.files[0].pk]
        self.assertEqual([entry['file_id'] for entry in loaded], expected_ids)
        self.assertEqual([call.args[0] for call in wrapper.call_args_list], expected_ids)
        self.assertEqual(self.parser.parse.call_count, 2)
        for call in wrapper.call_args_list:
            self.assertEqual(len(call.args), 3)
            self.assertEqual(call.args[2].owner_id, self.user.pk)
            self.assertEqual(call.args[2].pk, call.args[0])

    def test_multiple_empty_or_all_invalid_ids_need_no_queries(self):
        for ids in ([], ['bad', None, {}, [], '1.5', float('inf')]):
            with self.subTest(ids=ids), patch.object(
                _helpers, 'get_cached_parsed_file', wraps=services.get_cached_parsed_file,
            ) as wrapper:
                with self.assertNumQueries(0):
                    self.assertEqual(_helpers._load_files_from_request(self.request(), ids), [])
                wrapper.assert_not_called()

    def test_multiple_foreign_and_absent_ids_need_only_one_select(self):
        with patch.object(
            _helpers, 'get_cached_parsed_file', wraps=services.get_cached_parsed_file,
        ) as wrapper:
            with self.assertNumQueries(1):
                loaded = _helpers._load_files_from_request(
                    self.request(), [self.foreign.pk, self.absent_id],
                )
            self.assertEqual(loaded, [])
            wrapper.assert_not_called()
        self.parser.parse.assert_not_called()

    def test_multiple_out_of_range_ids_are_isolated_before_bulk_query(self):
        overflow, underflow = 2**63, -(2**63) - 1
        valid_id = self.files[0].pk
        for ids, expected_ids in (
            ([overflow, valid_id, str(underflow), str(valid_id)], [valid_id, valid_id]),
            ([overflow, underflow], []),
        ):
            with self.subTest(ids=ids), self.assertNumQueries(1 if expected_ids else 0):
                try:
                    loaded = _helpers._load_files_from_request(self.request(), ids)
                except OverflowError as exc:
                    self.fail(f'One out-of-range ID must not abort the batch: {exc}')
                self.assertEqual([entry['file_id'] for entry in loaded], expected_ids)

    def test_multiple_missing_disk_is_delegated_to_real_cache_wrapper(self):
        Path(self.files[0].file_path).unlink()
        ids = [file.pk for file in self.files[:2]]
        with patch.object(
            _helpers, 'get_cached_parsed_file', wraps=services.get_cached_parsed_file,
        ) as wrapper:
            loaded = _helpers._load_files_from_request(self.request(), ids)
        self.assertEqual([entry['file_id'] for entry in loaded], ids[1:])
        self.assertEqual([call.args[0] for call in wrapper.call_args_list], ids)
        self.parser.parse.assert_called_once_with(self.files[1].file_path)

    def test_multiple_parser_failures_do_not_discard_valid_files(self):
        def parse(path):
            if path == self.files[0].file_path:
                return None, {'parse_error': 'fixture'}
            if path == self.files[1].file_path:
                raise ValueError('synthetic parser failure')
            return self.payloads[path]

        self.parser.parse.side_effect = parse
        with self.assertLogs('apps.datafiles.services', level='WARNING'):
            loaded = _helpers._load_files_from_request(
                self.request(), [file.pk for file in self.files],
            )
        self.assertEqual([entry['file_id'] for entry in loaded], [self.files[2].pk])
        self.assertEqual(self.parser.parse.call_count, 3)

    @contextmanager
    def sqlite_parameter_limit(self, limit=8):
        if connection.vendor != 'sqlite':
            self.skipTest('Requires the real SQLite variable limit')
        connection.ensure_connection()
        raw = connection.connection
        if not hasattr(raw, 'setlimit'):
            self.skipTest('sqlite3.Connection.setlimit requires Python 3.11+')
        category = sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER
        previous_limit = raw.getlimit(category)
        previous_feature = connection.features.max_query_params
        try:
            # All fixture INSERTs must finish before lowering the actual limit.
            raw.setlimit(category, limit)
            with patch.object(type(connection.features), 'max_query_params', limit):
                self.assertEqual(raw.getlimit(category), limit)
                yield limit
        finally:
            raw.setlimit(category, previous_limit)
            self.assertEqual(raw.getlimit(category), previous_limit)
            self.assertEqual(connection.features.max_query_params, previous_feature)

    def assert_multiple_query_budget(self, ids, expected_ids, unique_count, limit):
        owner_params = DataFile.objects.filter(owner=self.user).query.sql_with_params()[1]
        self.assertEqual(len(owner_params), 1)
        budget = limit - len(owner_params) if limit else unique_count
        expected_sizes = [
            len(owner_params) + min(budget, unique_count - offset)
            for offset in range(0, unique_count, budget)
        ]
        executed = []

        def record(execute, sql, params, many, context):
            executed.append((sql, len(params)))
            return execute(sql, params, many, context)

        request = self.request()
        with connection.execute_wrapper(record), self.assertNumQueries(len(expected_sizes)):
            loaded = _helpers._load_files_from_request(request, ids)
        self.assertEqual([entry['file_id'] for entry in loaded], expected_ids)
        self.assertEqual([size for _, size in executed], expected_sizes)
        for sql, _ in executed:
            self.assertTrue(sql.lstrip().upper().startswith('SELECT'), sql)

    def test_sqlite_unbatched_bulk_really_exceeds_parameter_limit(self):
        files = self.files + [self.make_file(i, self.user) for i in range(5, 10)]
        ids = [file.pk for file in files]
        with self.sqlite_parameter_limit() as limit:
            self.assertEqual(len(ids), limit)
            # Both the old call and naive in_bulk(ids) forget the owner's slot.
            for explicit_ids in (False, True):
                with self.subTest(explicit_ids=explicit_ids):
                    queryset = DataFile.objects.filter(owner=self.user)
                    with self.assertRaisesRegex(OperationalError, 'too many SQL variables'):
                        if explicit_ids:
                            queryset.in_bulk(id_list=ids)
                        else:
                            queryset.filter(pk__in=ids).in_bulk()
            with self.assertNumQueries(1):
                rows = DataFile.objects.filter(owner=self.user).in_bulk(id_list=ids[:-1])
            self.assertEqual(set(rows), set(ids[:-1]))

    def test_multiple_sqlite_parameter_budget_includes_owner_at_boundary(self):
        files = self.files + [self.make_file(i, self.user) for i in range(5, 18)]
        with self.sqlite_parameter_limit() as limit:
            for count in (1, limit - 1, limit, 2 * limit):
                ids = [file.pk for file in files[:count]]
                with self.subTest(count=count):
                    self.assert_multiple_query_budget(ids, ids, count, limit)

    def test_multiple_sqlite_batches_preserve_mixed_order_and_duplicates(self):
        files = self.files + [self.make_file(i, self.user) for i in range(5, 18)]
        ordered = [file.pk for file in reversed(files)]
        expected_ids = [ordered[-1], *ordered, *ordered[:5], ordered[-1]]
        ids = [
            str(ordered[-1]), 'bad', self.foreign.pk, 2**63, *ordered,
            None, str(-(2**63) - 1), self.absent_id, {}, *ordered[:5],
            str(ordered[-1]), self.foreign.pk, self.absent_id,
        ]
        original_ids = deepcopy(ids)
        with self.sqlite_parameter_limit() as limit:
            # Only 18 valid unique IDs spend slots; forbidden/missing rows still
            # count in SQL, while invalid and out-of-range inputs do not.
            self.assert_multiple_query_budget(ids, expected_ids, len(files) + 2, limit)
        self.assertEqual(ids, original_ids)
        self.assertEqual(self.parser.parse.call_count, len(files))

    def test_multiple_unbounded_backend_uses_one_select_with_duplicates(self):
        ids = [file.pk for file in reversed(self.files)] * 4
        # Simulate an unbounded backend's budgeting, retaining real SQL execution.
        with patch.object(type(connection.features), 'max_query_params', None), patch.object(
            connection.ops, 'bulk_batch_size', side_effect=lambda fields, objs: len(objs),
        ):
            self.assert_multiple_query_budget(ids, ids, len(self.files), None)

    def test_multiple_unexpected_load_exception_remains_isolated_per_id(self):
        def load(file_id, owner_id, datafile=None):
            if file_id == self.files[0].pk:
                raise OSError('synthetic load failure')
            return services.get_cached_parsed_file(file_id, owner_id, datafile)

        with patch.object(_helpers, 'get_cached_parsed_file', side_effect=load):
            loaded = _helpers._load_files_from_request(
                self.request(), [file.pk for file in self.files],
            )
        self.assertEqual([entry['file_id'] for entry in loaded], [file.pk for file in self.files[1:]])

    def test_view_guard_responses_keep_status_and_error_envelope_for_body_and_query(self):
        for query in (False, True):
            for file_id, code in (
                (None, 'file_id_required'), ('abc', 'file_id_invalid'),
                (self.foreign.pk, 'file_not_found'), (self.absent_id, 'file_not_found'),
            ):
                with self.subTest(query=query, file_id=file_id):
                    payload = {} if file_id is None else {'file_id': file_id}
                    request = self.raw_request(payload, query=query)
                    response = AnalysisViewSet.as_view({'get': 'histogram', 'post': 'histogram'})(request)
                    response.render()
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.data, {'code': code, 'message': None, 'detail': None})
        self.parser.parse.assert_not_called()
