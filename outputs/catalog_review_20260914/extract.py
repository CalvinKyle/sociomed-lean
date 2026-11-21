import json
from pathlib import Path
import openpyxl

source = Path('/Users/calvinainebyona/Downloads/sociomed_master_2026-09-13.xlsx')
book = openpyxl.load_workbook(source, read_only=True, data_only=True)
data = {}
for sheet in book:
    rows = iter(sheet.values)
    headers = next(rows, ())
    data[sheet.title] = [dict(zip(headers, row)) for row in rows if any(value is not None for value in row)]
Path('/private/tmp/sociomed-review.EU7W2M/source.json').write_text(json.dumps({'source': source.name, 'data': data}, default=str))
print({key:len(rows) for key,rows in data.items()})
