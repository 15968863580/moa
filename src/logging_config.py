"""kaka_moa - 日志配置（按天分文件 + 错误日志分离，便于查询调用报错）"""

import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

# 日志目录（项目根目录下的 logs/）
LOG_DIR = Path(__file__).parent.parent / "logs"

# 日志格式
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


class DailyFileHandler(logging.FileHandler):
    """
    按天生成日志文件，文件名直接包含日期：{prefix}-YYYY-MM-DD.log

    日期切换（跨天）时自动创建新文件，旧文件按 backup_count 自动清理。
    """

    def __init__(self, filepath_prefix, backup_count=30, encoding='utf-8'):
        self.filepath_prefix = filepath_prefix
        self.backup_count = backup_count
        self._current_date = datetime.now().strftime('%Y-%m-%d')
        filename = f"{filepath_prefix}-{self._current_date}.log"
        super().__init__(filename, encoding=encoding, delay=False)

    def emit(self, record):
        today = datetime.now().strftime('%Y-%m-%d')
        if today != self._current_date:
            self._rotate(today)
        super().emit(record)

    def _rotate(self, new_date):
        if self.stream:
            self.stream.close()
            self.stream = None
        self._current_date = new_date
        self.baseFilename = f"{self.filepath_prefix}-{new_date}.log"
        self.stream = self._open()
        self._cleanup_old_files()

    def _cleanup_old_files(self):
        """删除超过 backup_count 天的日志文件"""
        log_dir = Path(self.filepath_prefix).parent
        prefix = Path(self.filepath_prefix).name
        pattern = re.compile(rf'^{re.escape(prefix)}-(\d{{4}}-\d{{2}}-\d{{2}})\.log$')
        cutoff = datetime.now() - timedelta(days=self.backup_count)
        for f in log_dir.iterdir():
            m = pattern.match(f.name)
            if m:
                try:
                    file_date = datetime.strptime(m.group(1), '%Y-%m-%d')
                    if file_date < cutoff:
                        f.unlink(missing_ok=True)
                except ValueError:
                    continue


def setup_logging(default_level: str = "INFO"):
    """
    配置全局日志：

    - 控制台输出
    - 全量日志按天分文件：logs/moa-YYYY-MM-DD.log（记录所有调用过程）
    - 错误日志按天分文件：logs/error-YYYY-MM-DD.log（仅 ERROR 及以上）
      独立存放，便于快速查询调用报错

    日志级别可通过环境变量 MOA_LOG_LEVEL 覆盖（DEBUG/INFO/WARNING/ERROR）。
    """
    level_name = os.getenv("MOA_LOG_LEVEL", default_level).upper()
    log_level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # 确保日志目录存在
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    # 1. 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 2. 全量日志文件（按天分文件，保留 30 天，记录所有调用过程）
    file_handler = DailyFileHandler(
        filepath_prefix=str(LOG_DIR / "moa"),
        backup_count=30,
        encoding='utf-8',
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 3. 错误日志文件（按天分文件，仅 ERROR 及以上，保留 30 天）
    #    独立存放于 logs/error-YYYY-MM-DD.log，便于快速查询调用报错
    error_handler = DailyFileHandler(
        filepath_prefix=str(LOG_DIR / "error"),
        backup_count=30,
        encoding='utf-8',
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)
