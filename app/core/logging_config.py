import logging
import logging.config
import sys
import asyncio

# Define a logging configuration dictionary
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonLogger',
            'timestamp': True
        },
    },
    'handlers': {
        'async_file_handler': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/audit_trail.log',
            'maxBytes': 10485760,   # 10MB
            'backupCount': 5,  
        },
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
            'level': 'INFO',
            'stream': 'ext://sys.stdout',
        },
    },
    'loggers': {
        '': {  # root logger
            'handlers': ['async_file_handler', 'console'],
            'level': 'INFO',
        },
    },
}

# Function to set up logging configuration
def setup_logging(correlation_id: str = "startup"):
    logging.config.dictConfig(LOGGING_CONFIG)
    logger = logging.getLogger(__name__)
    logger.info('Logging setup done', extra={'correlation_id': correlation_id})

# Example async function to demonstrate logging with correlation ID
async def log_with_correlation_id(correlation_id):
    logger = logging.getLogger(__name__)
    logger.info('Logging an event', extra={'correlation_id': correlation_id})


# Example usage
if __name__ == '__main__':
    correlations = ['abcd-1234', 'efgh-5678']  # Example correlation IDs
    for id in correlations:
        asyncio.run(log_with_correlation_id(id))
