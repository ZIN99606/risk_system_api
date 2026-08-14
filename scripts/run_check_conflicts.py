# scripts/run_check_conflicts.py
# -*- coding: utf-8 -*-
"""
独立运行冲突诊断，可直接在服务器上执行:
python scripts/run_check_conflicts.py
"""
import os
import sys
import pandas as pd
import numpy as np

# 将项目根目录加入 path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from app.core.check_conflicts import main as run_check

if __name__ == "__main__":
    print("🚀 启动冲突诊断（云端版）...")
    # 直接调用 main，或者重写这里的逻辑指向你已有的 check_conflicts.py
    # 但为了避免循环导入，建议在这里直接复制 check_conflicts 的核心逻辑
    # 或者简单调用它的 main 函数（如果你把 check_conflicts.py 改造成模块）
    
    # 简单方式：导入并运行
    run_check()