import logging
import json
import os

class CustomJSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            'time': self.formatTime(record),
            'level': record.levelname,
            'message': record.getMessage(),
            'filename': record.filename,
            'funcName': record.funcName,
            'lineno': record.lineno
        }
        return json.dumps(log_record)

def setup_logging(log_level=logging.INFO):
    # Create application directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)

    # Create file handler
    file_handler = logging.FileHandler('logs/app.log')
    file_handler.setLevel(log_level)
    file_handler.setFormatter(CustomJSONFormatter())

    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(CustomJSONFormatter())

    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

if __name__ == '__main__':
    setup_logging()  
    logging.info('Logging setup complete.')  
    logging.error('This is an error message.')  
    logging.debug('This debug message will appear in the logs too if the level is set appropriately.')  
