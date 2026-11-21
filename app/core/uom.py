"""Conservative buyer units; raw supplier packaging codes never leave the bot."""
import json
import re
from pathlib import Path

LABELS = json.loads((Path(__file__).parents[1] / 'content/uom_labels.json').read_text())


def buyer_uom(value):
    key = str(value or '').strip()
    if key.upper() in LABELS:
        return LABELS[key.upper()]['label']
    if re.fullmatch(r'(?:units?|pieces?|box(?:es)?|packs?|pairs?|sets?|rolls?|bottles?|bags?|kits?|cartons?)(?: of \d+)?', key, re.I):
        return key
    return 'unit'
