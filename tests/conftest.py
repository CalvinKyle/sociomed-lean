"""Never load developer/live credentials while running the offline suite."""
import os
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['OPS_SHEET_NAME'] = ''
os.environ['SHEETS_AUTO_SYNC_ENABLED'] = 'false'
