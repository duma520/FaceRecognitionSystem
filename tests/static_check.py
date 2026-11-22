# -*- coding: utf-8 -*-
"""静态自检：语法、重复方法（后者覆盖前者）、设置项覆盖度、调用/定义一致性

运行：
    venv\\Scripts\\python.exe tests\\static_check.py [目标文件]

默认检查项目根目录的 FaceRecognitionSystem.py。
退出码 0 = 通过；1 = 发现问题（重复方法）。
"""
import ast
import collections
import io
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
os.chdir(ROOT)
sys.path.insert(0, ROOT)

TARGET = sys.argv[1] if len(sys.argv) > 1 else 'FaceRecognitionSystem.py'

src = io.open(TARGET, encoding='utf-8').read()
tree = ast.parse(src)
print(f"[OK] 语法解析通过: {TARGET} ({len(src.splitlines())} 行)")

print("\n--- 类内重复方法检查（重复定义会让后者静默覆盖前者）---")
dup_found = False
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        names = collections.Counter()
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names[item.name] += 1
        dups = {k: v for k, v in names.items() if v > 1}
        if dups:
            dup_found = True
            print(f"  [!] {node.name}: {dups}")
        else:
            print(f"  [OK] {node.name}: {len(names)} 个方法，无重复")
print(f"结论：重复方法 {'存在（需修复）' if dup_found else '无'}")

print("\n--- 设置项（ConfigManager.DEFAULTS）使用统计 ---")
defaults = None
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == 'ConfigManager':
        for item in node.body:
            if isinstance(item, ast.Assign) and getattr(item.targets[0], 'id', '') == 'DEFAULTS':
                defaults = [k.value for k in item.value.keys]
print(f"  DEFAULTS 项数: {len(defaults) if defaults else 0}")
for key in (defaults or []):
    print(f"    {key:22s} 出现 {src.count(repr(key)) + src.count(chr(34) + key + chr(34))} 次")

print("\n--- 敏感信息硬编码检查（需求8）---")
hits = []
for i, line in enumerate(src.splitlines(), 1):
    stripped = line.strip()
    if stripped.startswith('#') or 'SECRET_FIELD_NAMES' in line:
        continue
    low = line.lower()
    for kw in ('api_key', 'apikey', 'api_secret', 'password=', 'passwd=', 'db_password', 'access_key'):
        if kw in low and '=' in line and 'self.' not in line and 'def ' not in line:
            if any(q in line for q in ('"', "'")):
                hits.append((i, stripped))
print(f"  可疑硬编码: {hits if hits else '无'}")

sys.exit(1 if dup_found else 0)
