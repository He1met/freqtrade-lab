Console 用解析后的 Python 路径启动 Development 和 Holdout worker 时，venv 软链接会变成基础解释器，导致已安装在 venv 的依赖不可导入。本修改保留原绝对调用路径，同时验证其目标是存在且可执行的正规文件。

新增真实临时 venv 回归，分别走两个 controller 调用点，验证子进程 `sys.prefix` 和仅 venv 可见的依赖；覆盖无效目标。与相关 D/H HTTP 回归合计 **38 passed，0 skip**，`git diff --check` 通过，无策略执行。

关联 #98。本修复不恢复或重放已失败的 Development；其技术 FAILED/NULL 与同产物 POSTHOC_DIAGNOSTIC_ONLY 负例保留，H/Stress 未执行。
