import logging
from config import settings

def setup_logger(thread_id: str, level=logging.INFO) -> str:
    """Configures console and file logging dynamically for each thread run."""
    log_format = '%(asctime)s - %(levelname)s %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    formatter = logging.Formatter(log_format, datefmt=date_format)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Clear out any old handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    # Setup File Handler
    log_file = settings.LOG_DIR / f"{thread_id}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Setup Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    return str(log_file)