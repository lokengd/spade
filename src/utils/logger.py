from datetime import datetime
import logging
from pathlib import Path
from typing import Tuple, Dict
from config import settings

# Global to store the current thread's log directory
_current_log_dir: Path = None

def get_current_log_dir() -> Path:
    """Returns the current log directory for the active thread."""
    global _current_log_dir
    return _current_log_dir

def get_loop_info(state: dict, include_inner: bool = True) -> Tuple[str, Dict[str, int]]:
    """
    Centralized helper to extract N, M, V values.
    Returns a tuple of (formatted_string, info_dict).
    """
    n = state.get("outer_loop_count", 1)
    m = state.get("inner_loop_count", 1)
    v = state.get("current_patch_version", 1)
    
    info_dict = {"n": n, "m": m, "v": v}
    
    if include_inner:
        info_str = f"[N={n}/{settings.N_OUTER_LOOPS}] [M={m}/{settings.M_INNER_LOOPS}] [V={v}/{settings.V_PATIENCE}]"
    else:
        info_str = f"[N={n}/{settings.N_OUTER_LOOPS}]"
    
    return info_str, info_dict

def setup_logger(thread_id: str, level=logging.INFO) -> str:
    """Configures console and file logging dynamically for each thread run."""
    global _current_log_dir

    log_format = '%(asctime)s - %(levelname)s %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    formatter = logging.Formatter(log_format, datefmt=date_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear out any old handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Setup File Handler
    # Format the folder: e.g., YYYYMMDD_HHMISS-thread_id
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")    
    folder_name = f"{timestamp}-{thread_id}"
    _current_log_dir = settings.LOG_DIR / folder_name
    _current_log_dir.mkdir(parents=True, exist_ok=True)

    # The log file itself inside the subfolder
    filename = f"{folder_name}.log"
    log_file = _current_log_dir / filename

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
