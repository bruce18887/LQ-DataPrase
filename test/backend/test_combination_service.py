from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.datafiles.combination_service import (
    managed_tags_for,
    normalize_batch_no,
    normalize_combination_name,
    resolve_batch_no,
)
from apps.datafiles.models import DataCombination, DataFile
from django.contrib.auth import get_user_model


class CombinationServiceTests(TestCase):
    def test_managed_tags_are_derived_from_combination_and_batch(self):
        self.assertEqual(managed_tags_for('gage', ''), ['gage'])
        self.assertEqual(
            managed_tags_for('gage', 'BE01-2608130015'),
            ['gage', 'gage / BE01-2608130015'],
        )
        self.assertEqual(managed_tags_for(None, 'BE01-2608130015'), [])

    def test_normalization_trims_and_rejects_separators(self):
        self.assertEqual(normalize_combination_name('  Gage Lab  '), 'Gage Lab')
        self.assertEqual(normalize_batch_no('  BE01-2608130015 '), 'BE01-2608130015')
        for raw in ('a/b', 'a\\b', 'a\nb'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_combination_name(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_batch_no(raw)

    def test_batch_number_prefers_explicit_then_metadata(self):
        self.assertEqual(resolve_batch_no('MANUAL', {'lot_id': 'LOT'}), 'MANUAL')
        self.assertEqual(resolve_batch_no('', {'lot_id': 'LOT'}), 'LOT')
        self.assertEqual(resolve_batch_no('', {'lot_id': None}), '')
        self.assertEqual(resolve_batch_no('', {'lot_id': 123}), '')
        self.assertEqual(resolve_batch_no('', {'lot_id': 'BAD/LOT'}), '')

    def test_combination_name_is_case_insensitive_unique_per_owner(self):
        User = get_user_model()
        owner = User.objects.create_user('combo_owner', password='x')
        other = User.objects.create_user('combo_other', password='x')
        DataCombination.objects.create(owner=owner, name='Gage')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DataCombination.objects.create(owner=owner, name='gage')
        DataCombination.objects.create(owner=other, name='gage')

    def test_delete_combination_only_clears_file_relation(self):
        User = get_user_model()
        owner = User.objects.create_user('combo_delete', password='x')
        combo = DataCombination.objects.create(owner=owner, name='gage')
        row = DataFile.objects.create(
            owner=owner, filename='a.csv', file_path='data/combo_delete/single/a.csv',
            file_size=1, format_type='CTA8290D', combination=combo,
            batch_no='BE01-2608130015', tags=['manual'],
        )
        combo.delete()
        row.refresh_from_db()
        self.assertIsNone(row.combination)
        self.assertEqual(row.batch_no, 'BE01-2608130015')
        self.assertEqual(row.tags, ['manual'])
