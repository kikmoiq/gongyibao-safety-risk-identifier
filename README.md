# 工艺包安全风险辨识系统（Demo）

**版本：v0.3.1-demo（2026-09-10）**　详见 [CHANGELOG.md](CHANGELOG.md) 与 `VERSION`

> ## ⚠️ 免责声明 / 密级提示
>
> - 本仓库为**方法演示与技术验证**用途的本地工具 Demo，**不构成任何安全评价结论**。
> - 仓库内全部示例工艺包均为**行业通用技术常识的脱敏虚构文档**，**不含**任何单位的真实产能、配方、设备位号、安全距离等敏感信息；文件首行均标注“演示示例 · 脱敏/虚构”。
> - 工程实际应用时，具体物料、产能、布置与标准号须按所在单位**保密规定**另行脱敏与管理。
> - 禁止将本工具用于制毒、制爆或任何违法违规目的；火炸药类结果仅供**安全仪表与风险辨识**研究参考。
> - 提交历史中**不包含** `config.json`（含 API Key），见 `.gitignore`。

## 📁 目录结构

```
app/                 FastAPI 后端 + 辨识引擎
  engine/            ingest（文档摄取）｜rules（规则）｜robots（机器人）
                     references（参考文件）｜flow（工序流程）｜fta（故障树）
                     reportdoc（Word/HTML 报告）｜orchestrator（编排）
static/              原生前端（index.html / js / css，无框架、无 CDN、离线可用）
示例数据/            7 个演示工艺包（.md）+ 机器人选型图（robot_media/）
docs/                示例报告（Word/JSON）与截图素材
archive_batch.py     批量辨识 + 归档（改 PKGS 即可增删工艺包）
archive_results.py   单包辨识 + 归档
selftest.py          自检脚本
build_usage_docx.py  使用说明 → Word
START.bat / run.bat  一键启动
config.example.json  配置模板（无密钥）
```

## 🧪 示例数据（可直接拿来试）

| # | 演示工艺包 | 规模 | 看点 |
|---|---|---|---|
| 1 | 硝化棉单基发射药**自动化生产线** | 68 条 | 5 台机器人（含 AGV）+ 选型图 + 20 项设计依据 |
| 2 | 硝化棉单基发射药生产线 | 45 条 | 常规线基线 |
| 3 | 双基发射药连续化生产线 | 42 条 | 极敏感物料（硝化甘油）+ 13 道工序主链 |
| 4 | 起爆药（叠氮化铅·四氮烯）合成线 | 19 条 | 无自动化台账，全部靠军品专项规则 |
| 5 | 工业雷管装配生产线 | 36 条 | 起爆药 + 装药压合工位的机器人风险 |
| 6 | 药粒包覆与混同包装线 | 29 条 | **纯叙事无风险表**，考验文本回退路径 |
| 7 | 成品储存与厂内智能输送线 | 35 条 | **区域命名体系** + 立体库/AGV |

用法：界面点「上传文件」选 `示例数据/*.md`，或直接执行 `python archive_batch.py` 一次跑完 7 个包。

## 🚀 快速打开（推荐）
1. 双击 **`START.bat`**（或桌面快捷方式「工艺包安全风险辨识系统」）；
2. 稍候浏览器自动打开 http://127.0.0.1:8000 ；
3. 关闭该命令行窗口即停止服务。

> 首次运行会自动创建 `.venv` 并安装依赖（需已安装 Python 3.10+，本机用 `py`）；
> 之后每次启动仅需 1~3 秒。

本地部署、浏览器访问的**安全风险辨识**工具 Demo。上传（或粘贴）任意工艺包文档
（.md / .docx / 纯文本），系统按《安全风险辨识方案》的方法自动：
- 读取工艺包自带**风险场景表**、**SDS 物料键值表**并逐条成条目；
- 扫描**联锁/安全阈值**（温度、压力、浓度等）、**点火源**、**作业活动**等线索；
- 识别**自动化装备/机器人**（防爆机器人、桁架机器人、机械手、AGV），
  生成“一条目一页”的机器人条目（含减少操作人数、机器人新增风险、选型参数与图片）；
- 汇总**参考文件/设计依据**（国标、行标、规范、参考书）并分类去重；
- 可选接入 **OpenAI 兼容大模型 API** 对“完全不同工艺包”做智能补名/后果判定；
- 输出报告页：**概览（风险可视化）｜工艺流程图（可交互）｜故障树 FTA｜机器人｜参考文件｜报告预览（可下载 Word / 打印 PDF）｜条目列表（条目总表＋一条目一页）**。

> 详细操作、REST 接口与边界说明见同目录 **《使用说明.md》**。

> 定位：Demo / 内部测试工具。结果仅供风险辨识与研发验证，正式安全评价请以专项分析（HAZOP/LOPA/FTA/QRA 等）与现行标准为准。

---

## 1. 运行

Windows（双击）：
```
run.bat
```
或手动：
```
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
浏览器打开 http://127.0.0.1:8000

依赖：`fastapi`、`uvicorn[standard]`、`python-multipart`、`httpx`、`python-docx`（见 `requirements.txt`）。

## 2. 接入大模型 API（可选）

软件右上角 **⚙️ API 配置** 填三项（OpenAI 兼容）：
- `Base URL`：如 `https://api.deepseek.com/v1`（或你的网关/本地代理地址）
- `API Key`
- `模型名`：如 `deepseek-chat`

分析时勾选 **大模型增强** 即可；未配置 key 时自动回退纯本地规则引擎。
配置保存在项目根 `config.json`（key 读取时打码）。也可直接编辑 `config.json`。

## 3. 软件自身提供的 REST 接口

| 接口 | 说明 |
| --- | --- |
| `GET  /api/health` | 健康检查 |
| `GET  /api/config` / `POST /api/config` | 读写配置 |
| `POST /api/analyze/text` | `{text, filename?, use_llm?}` 分析文本 |
| `POST /api/analyze/upload` | multipart：`file`(.md/.docx/.txt)、`use_llm` |
| `GET  /api/analyze/demo` | 分析演示样例（`config.json.demo_package_path`，默认己二腈工艺包） |
| `GET  /api/reports` / `GET /api/report/{id}` | 报告列表 / 整份 JSON |
| `GET  /api/report/{id}/items?page=&size=` | 条目分页 |
| `DELETE /api/report/{id}` | 删除报告 |
| `GET  /api/export/{id}` | 导出整份报告 JSON |

> 说明：报告保存在**服务进程内存**中，重启即清空；Demo 阶段未接数据库。

## 4. 工程结构

```
安全风险辨识系统/
├─ app/
│  ├─ main.py              # FastAPI 入口 + REST 接口 + 静态页
│  ├─ config.py            # config.json 读写（含 LLM 配置）
│  ├─ engine/
│  │  ├─ ingest.py         # .docx/.md/文本 → 规范化文本（含 HTML 表格归一化）
│  │  ├─ rules.py          # 本地规则辨识引擎（场景表/SDS/联锁/点火源/作业）
│  │  ├─ flow.py           # 工序流程图抽取（主链/辅助/回流/工序描述）
│  │  ├─ fta.py            # 数据驱动初筛故障树（顶-中间-场景-底事件）
│  │  ├─ llm.py            # OpenAI 兼容大模型增强
│  │  ├─ models.py         # 条目/报告数据模型
│  │  └─ orchestrator.py   # 编排：规则 + 可选 LLM → 报告（含 flow/fault_tree）
├─ static/                 # 前端（无框架、离线可用）
│  ├─ index.html
│  ├─ css/style.css
│  └─ js/app.js
├─ data/演示样例_工艺包.md  # 内置精简演示（无本地工艺包时回退）
├─ config.example.json
├─ requirements.txt
├─ run.bat
└─ 使用说明.md              # 用户操作手册
```

## 5. 已知边界（Demo）

- 规则引擎**能自动命名常见化工物料（SDS 表）**，但面对“完全不同/纯叙述工艺包”时，
  未知物料名、感度等参数需大模型或人工补名（报告会给出“待确认”提示）。
- .docx 上传后自动按正文顺序转文本；图表/图片不参与分析。
- 单条目标题取自原文片段，措辞未经安全专业复核，属初筛结论。
- 军品（火炸药等）感度/殉爆/量-距离等**军品专项**维度为预留类别，需在结果基础上叠加专项辨识。

## 6. 测试方法

用“完全不同”的工艺包验证：
1. 把新工艺包另存为 `.md` 或 `.docx`；
2. 打开本系统 → 上传 → 勾选/不勾选大模型增强 → 开始辨识；
3. 在报告中核对：物料条目是否被命名、风险场景表是否被逐行拆出、
   联锁/作业条目是否齐全；必要时配置 LLM 后重跑对比覆盖率。
