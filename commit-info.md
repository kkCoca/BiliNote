## feat(batch): add bilibili batch note generation and opencli integration by AI Coding

### 修改原因
为真实 B 站合集/空间链接补齐批量笔记生成能力，并修复前端表单残留导致合集误走单视频流程的问题。

### 解决方式
新增 URL 探测、批量提交与 OpenCLI sidecar 流程，补充转写与容器稳定性修复，同时统一迁移仓库公开链接与部署文档。

### 变更概要

| 模块 | 新增 | 修改 | 删除 | 说明 |
|---|---|---|---|---|
| `backend/app/routers/` | 1 | 1 | 0 | 新增批量接口，阻止合集链接误走单任务接口 |
| `backend/app/services/` | 1 | 2 | 0 | 增加批量状态管理，并复用共享执行器与懒加载转写链路 |
| `backend/app/utils/` | 4 | 0 | 0 | 增加 URL 探测、OpenCLI sidecar 调用与 execstack 修复 |
| `backend/app/transcriber/` | 0 | 4 | 0 | 提升 whisper、groq、bcut 初始化与失败回退稳定性 |
| `opencli/` | 3 | 0 | 0 | 新增 sidecar 容器、启动脚本与空间列表抓取服务 |
| `BillNote_frontend/src/` | 1 | 2 | 0 | 增加批量 API 客户端，前端支持预览勾选与批量提交 |
| `backend/tests/` | 3 | 1 | 0 | 增加批量与 URL 探测测试，修正执行器测试 |
| `docs/` | 5 | 0 | 0 | 补充部署、OpenCLI 和实现计划文档，并加入配图 |
| 仓库元数据与部署 | 2 | 8 | 0 | 更新 README、Issue 模板、Docker/Compose/Nginx 与 GitHub/GHCR 链接 |

### 代码统计
- 暂存代码文件：26 个
- 新增：2124 行
- 删除：218 行
- 总变更：2342 行
- 全部暂存文件：42 个，整体变更 `+14565 / -232`

### 合并注意事项
- **影响功能点**: B 站真实合集/空间链接现在会先解析列表并支持批量提交；普通 BV 视频页仍保留单视频生成路径。
- **验证方式**: `python3 -m unittest backend.tests.test_batch_manager backend.tests.test_batch_routes backend.tests.test_url_detector backend.tests.test_task_serial_executor` 通过；`pnpm build` 通过；`pnpm lint` 仍因仓库既有问题失败。
