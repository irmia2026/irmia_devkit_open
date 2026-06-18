"""
registry_split — 注册表拆分方案。
将原 _registry.py 拆分为 4 个文件，解决上帝模块问题。

文件结构：
  _registry_core.py   — 核心基础设施（make_tool, _err, _unwrap, _run_sync, 工具基类）
  _registry_groups.py  — 工具分组定义（TOOL_GROUPS, 分组描述）
  _registry_tools.py   — 63 个工具注册（make_tool() 调用）
  _registry.py         — 兼容入口（导入并导出所有符号，保持向后兼容）

迁移步骤：
  1. 创建 _registry_core.py（从 _registry.py 提取核心代码）
  2. 创建 _registry_groups.py（从 _registry.py 提取分组）
  3. 创建 _registry_tools.py（从 _registry.py 提取工具注册）
  4. 重写 _registry.py 为兼容入口
  5. 更新所有 import 路径（main.py, tests/）
  6. 运行测试验证

风险：
  - 需要更新所有 import _registry 的地方
  - 测试中的 mock 可能需要调整
  - 需要确保 AstrBot 加载时不会循环导入
"""
