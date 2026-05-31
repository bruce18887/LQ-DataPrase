import csv
import os

from celery import shared_task

from apps.datafiles.models import DataFile, ParseHistory


@shared_task
def parse_data_file_task(datafile_id):
    try:
        datafile = DataFile.objects.get(pk=datafile_id)
        datafile.status = 'parsing'
        datafile.save(update_fields=['status', 'updated_at'])

        if not os.path.exists(datafile.file_path):
            datafile.status = 'error'
            datafile.metadata = {'error': 'File not found on disk'}
            datafile.save(update_fields=['status', 'metadata', 'updated_at'])
            return

        with open(datafile.file_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            all_rows = list(reader)

        units = []
        mins = {}
        maxs = {}

        for row in all_rows:
            for col in headers:
                value = row.get(col, '')
                try:
                    num_val = float(value)
                    if col not in mins:
                        mins[col] = num_val
                        maxs[col] = num_val
                    else:
                        mins[col] = min(mins[col], num_val)
                        maxs[col] = max(maxs[col], num_val)
                except (ValueError, TypeError):
                    pass

            unit_col = next(
                (h for h in headers if h.lower() in ('unit', 'units', 'unit_name')),
                None,
            )
            if unit_col and row.get(unit_col):
                val = row[unit_col].strip()
                if val and val not in units:
                    units.append(val)

        datafile.metadata = {
            'units': units,
            'mins': mins,
            'maxs': maxs,
        }
        datafile.row_count = len(all_rows)
        datafile.col_count = len(headers)
        datafile.status = 'ready'
        datafile.save()

        ParseHistory.objects.create(
            user=datafile.owner,
            datafile=datafile,
            filename=datafile.filename,
            filepath=datafile.file_path,
            format_type=datafile.format_type,
            rows=len(all_rows),
            cols=len(headers),
        )

    except DataFile.DoesNotExist:
        pass
    except Exception as e:
        try:
            datafile = DataFile.objects.get(pk=datafile_id)
            datafile.status = 'error'
            datafile.metadata = {'error': str(e)}
            datafile.save(update_fields=['status', 'metadata', 'updated_at'])
        except DataFile.DoesNotExist:
            pass
