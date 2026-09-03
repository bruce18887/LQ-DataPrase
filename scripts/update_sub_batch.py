#!/usr/bin/env python
"""Update sub_batch field for existing batch files.

This script extracts the sub_batch (subdirectory name) from the file_path
and updates the database record.
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
django.setup()

from apps.datafiles.models import DataFile


def update_sub_batch():
    """Update sub_batch field for all batch files."""
    # Get all batch files with empty sub_batch
    files = DataFile.objects.filter(file_type='batch', sub_batch='')
    print(f'Found {files.count()} batch files with empty sub_batch')

    updated = 0
    for f in files:
        # Extract batch directory and sub_batch from file_path
        # Path format: media/data/<username>/batch/<batch_name>/<sub_batch>/<filename>
        parts = f.file_path.replace('\\', '/').split('/')

        # Find 'batch' in path
        try:
            batch_idx = parts.index('batch')
            if batch_idx + 2 < len(parts) - 1:
                # batch_name is parts[batch_idx + 1]
                # sub_batch is parts[batch_idx + 2]
                batch_name = parts[batch_idx + 1]
                sub_batch = parts[batch_idx + 2]

                # Verify this matches the stored batch_name
                if f.batch_name == batch_name:
                    f.sub_batch = sub_batch
                    f.save(update_fields=['sub_batch'])
                    updated += 1
                    print(f'  Updated {f.filename}: sub_batch={sub_batch}')
                else:
                    print(f'  Skip {f.filename}: batch_name mismatch')
            else:
                print(f'  Skip {f.filename}: no sub_batch in path')
        except (ValueError, IndexError) as e:
            print(f'  Skip {f.filename}: {e}')

    print(f'\nUpdated {updated} records')


if __name__ == '__main__':
    update_sub_batch()
