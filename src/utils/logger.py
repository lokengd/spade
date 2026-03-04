from datetime import datetime
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
    # Format the filename: e.g., YYYYMMDD_HHMISS-[thread_id].log
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")    
    filename = f"{timestamp}-{thread_id}.log"
    log_file = settings.LOG_DIR / filename
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Setup Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    return str(log_file) # Return the log file path


def log(message: str, caller: str = "Main", level: int = logging.INFO):
    logger = logging.getLogger() 
    logger.log(level, f"[{caller}] {message}")

def get_log_header(thread_id: str) -> str:
    width = 40
    lines = [
        "",
        "*" * width,
        f"SPADE Run: {thread_id}",
        "-" * width,
        f"Orchestration Parameters:",
        f" K (Top-Patterns)     : {settings.K_PATTERNS}",
        f" N (Outer Loops)      : {settings.N_OUTER_LOOPS}",
        f" M (Inner Loops)      : {settings.M_INNER_LOOPS}",
        f" V (Version Patience) : {settings.V_PATIENCE}",
        "*" * width,
    ]
    return "\n".join(lines)


def get_memory_state(shared_memory_state: dict) -> str:
    """Returns the shared memory state as a formatted string for logging."""
    width = 40
    lines = [
        "",
        "=" * width,
        "SHARED MEMORY STATE",
        "-" * width
    ]
    
    for key, value in shared_memory_state.items():
        # Special handling for metrics to make them look nice
        if key == "total_metrics" and isinstance(value, dict):
            lines.append(f"{key}:")
            for m_key, m_val in value.items():
                lines.append(f" {m_key}: {m_val}")
        else:
            lines.append(f"{key}: {value}")

    lines.append("=" * width)
    lines.append("")
    return "\n".join(lines)