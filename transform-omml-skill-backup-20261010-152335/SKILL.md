---
name: transform-omml
description: 将 WPS/Word 文档中的 OMML（公式构建器）公式批量转换为 MathType 可编辑公式。触发词：transformOMML：《文章名称》——触发后在当前目录查找该文章（.docx），并调用内置脚本把文中全部 OMML 公式转换为 MathType 格式。也适用于"把文档里的公式转成 MathType 可编辑"等同类请求。
agent_created: true
---

# transform-omml：OMML → MathType 批量转换

## 用途

把 WPS 文字（或 Word）文档中用内置公式编辑器制作的 OMML 公式，批量转换为双击即可用 MathType 编辑的 OLE 公式。转换带自动备份、不自动保存，安全可回滚。

## 触发方式

- 精确触发：`transformOMML：《文章名称》`
- 语义触发：用户要求把某文档里的公式"转成 MathType 可编辑/能双击编辑的公式"。

## 前置条件（缺一先修复）

1. 本机装有 WPS 文字，且 MathType 选项卡可用（点击"内联"能弹出 MathType 窗口）。
2. WPS 为 32 位时，其 `office6\startup` 目录必须是 **32 位**加载项：`MathPage.wll`（约 739,840 B）+ `MathType Commands 2016.dotm`（约 950,713 B）。来源：MathType 安装目录下 `Office Support\32\` 与 `MathPage\32\`。位宽不匹配会导致 VBA 编译报错（如 CallbackGuard / IsMathInputPanelAvailable），先替换修复再转换。
3. WPS 文字正在运行（脚本通过 COM `GetActiveObject` 附加到运行实例，无法冷启动）。

## 执行流程

1. **解析目标文章**：去掉《》得到关键词，在当前工作目录递归查找匹配的 `*.docx`（先精确后模糊；多个匹配取修改时间最新者，歧义时询问用户）。排除 `~$*` 临时锁文件和 `*.bak` 备份。
2. **运行转换脚本**（脚本已内置在本技能中，直接调用）：

   ```powershell
   powershell -ExecutionPolicy Bypass -File "<本技能目录>\scripts\Convert-OMML-to-MathType.ps1" -DocPath "<docx 完整路径>"
   ```

   - 脚本行为：附加到 WPS（`Kwps.Application`）→ 定位/打开目标文档 → 统计 OMML 数量 → 备份原文件（`*.omml-backup-时间戳.bak`）→ 调用 MathType 宏 `DoConvertEquations`（equationTypes=8，仅 OMML；整篇文档；无弹窗；目标为 MathType OLE）→ 输出 `RESULT total=N remaining=M backup=路径`。
   - 若终端/沙箱策略拦截 COM 调用，换用不受限的 shell 或请用户在普通 PowerShell 窗口手动执行同一命令。
3. **判定结果**：
   - 退出码 0 且 `remaining=0`：全部转换成功。
   - 退出码 2 或 `remaining>0`：部分公式未转换，可手动用 MathType 选项卡"转换公式"补转。
   - 退出码 1：按 stderr 提示处理（常见：WPS 未运行 → 先启动 WPS 再重跑）。
4. **收尾提醒**：转换只在内存文档生效。提示用户在 WPS 中检查排版后按 Ctrl+S 保存；不满意则"不保存关闭"，备份文件可完整还原。向用户报告备份路径。

## 原理备忘（排障用）

- 转换入口是加载项内免对话框宏 `DoConvertEquations(showStats, equationTypes, selectionOnly, promptUser, translatorName, translatorOptions, count)`；`equationTypes` 位掩码：1=MathType、2=EQ 域、4=文本公式、8=OMML；`translatorName=""` 表示转成 MathType OLE。
- WPS 文字 COM ProgID：`Kwps.Application`。
- 光标/选区位于 OMML 公式内时，MathType 插入类命令会拒绝执行（"This command does not work inside Equation Builder equations"），属设计行为，非故障。
