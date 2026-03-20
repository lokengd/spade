from datetime import datetime
import logging
from pathlib import Path
from typing import Tuple, Dict, Optional
from src.core import settings

# Global to store the current session and thread log directory
_session_log_dir: Path = None
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

def setup_logger(thread_id: str = "Main", level=logging.INFO) -> str:
    """
    Configures console and file logging dynamically. 
    Groups all thread logs under a single session directory created on the first call.
    """
    global _session_log_dir, _current_log_dir

    log_format = '%(asctime)s - %(levelname)s %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    formatter = logging.Formatter(log_format, datefmt=date_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Initialize Session Directory (Once per execution)
    if _session_log_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        _session_log_dir = settings.LOG_DIR / f"session_{timestamp}"
        _session_log_dir.mkdir(parents=True, exist_ok=True)

    # Clear out any old handlers (to switch files)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Setup Console Handler (Always present)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Setup File Handler for the specific thread
    # Thread logs are stored in subfolders.
    _current_log_dir = _session_log_dir / thread_id
    _current_log_dir.mkdir(parents=True, exist_ok=True)

    log_file = _current_log_dir / f"{thread_id}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return str(log_file)


def log(message: str, caller: str = "Main", level: int = logging.INFO):
    logger = logging.getLogger() 
    # If no handlers, e.g. log() called before setup_logger, default to a simple basicConfig to avoid losing logs.
    if not logger.handlers:
        logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s [%(name)s] %(message)s')
    
    logger.log(level, f"[{caller}] {message}")

def get_log_header(experiment_id: str) -> str:
    width = 40
    lines = [
        "",
        "*" * width,
        f"SPADE Experiment: {experiment_id}",
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
    from src.utils.state_printer import StatePrinter
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        printer = StatePrinter()
        printer.print_state(shared_memory_state)
    return f.getvalue()
