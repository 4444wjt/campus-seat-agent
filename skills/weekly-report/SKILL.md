---
name: weekly-report
description: 把用户本周的自习室预约整理成 Markdown 周报并给出学习安排建议。用户要求“周报”“本周总结”“整理本周预约”时使用。
---

# 自习周报

按顺序执行：

1. 调用 `my_bookings(include_past=True)` 获取全部预约，只保留日期在系统提示词中“本周”范围内的记录。
2. 只依据这些本周记录，写 2–3 条学习安排建议，格式参考 `template.md`。不要编造数据中没有的信息，不要引用本周以外的预约。
3. 调用 `export_weekly_report(note=建议文本)` 生成周报文件。
4. 告诉用户文件路径，并用一两句话概括本周自习情况；次数等统计数字以 `export_weekly_report` 返回的结果为准。
