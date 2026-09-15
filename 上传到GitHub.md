# 上传到 GitHub · 操作指南

> 目标仓库内容：**本系统代码**（不含 `.venv`、不含 `config.json`、不含发布包与运行产物）

---

## 0. 当前环境检查结果（2026-09-15 · 已完成上传）

| 项目 | 状态 |
|---|---|
| `git` | ✅ 已安装（2.55.0，`C:\Program Files\Git\cmd\git.exe`，winget 安装） |
| `gh`（GitHub CLI） | ✅ 已安装（2.100.0，`C:\Program Files\GitHub CLI\gh.exe`） |
| 本目录是否 git 仓库 | ✅ 是（`main` 分支，4 次提交，最新 `5308d3a`） |
| 网络 | ⚠️ github.com 直连被阻断 → 已给 git 配置本机代理 `127.0.0.1:7890`（见下） |
| `config.json` | ⚠️ **含真实 API Key → 已加入 `.gitignore`；推送前后均核对未被跟踪** |

### 0.1 上传结果（2026-09-15 完成）

| 项 | 值 |
|---|---|
| 仓库地址 | <https://github.com/kikmoiq/gongyibao-safety-risk-identifier> |
| 账号 | `kikmoiq`（注意：仓库内既有提交的作者是 `talker0000`，与此账号不同名） |
| 可见性 | **Public 公开**（如需转私有：`gh repo edit --visibility private`） |
| 分支 / 提交 | `main` @ `5308d3a`（4 次提交） |
| 远端文件数 | 81（含 7 个演示工艺包与选型图） |
| 已排除 | `config.json`、`.venv/`、`__pycache__/`（已用 API 逐项核对为空） |

### 0.2 网络代理（本机必读）

本机 `github.com` 直连不通（**GET 有时通、POST/设备授权必被重置**），需走本机代理：

```powershell
git config --global http.proxy  http://127.0.0.1:7890
git config --global https.proxy http://127.0.0.1:7890
# gh 依赖环境变量：
$env:HTTPS_PROXY='http://127.0.0.1:7890'; $env:HTTP_PROXY='http://127.0.0.1:7890'; $env:NO_PROXY='127.0.0.1,localhost'
```

> 撤销代理：`git config --global --unset http.proxy`（https.proxy 同理）

---

## 1. 先安装 Git（二选一）

**方式 A：winget（推荐，在你自己的终端里运行，可能会弹 UAC）**

```powershell
winget install --id Git.Git -e --source winget
winget install --id GitHub.cli -e --source winget
```

装完后**重开一个终端**，验证：

```powershell
git --version
gh --version
```

**方式 B：手动下载** <https://git-scm.com/download/win>

---

## 2. 登录 GitHub（这一步必须你本人操作）

```powershell
gh auth login
```

按提示选择：`GitHub.com` → `HTTPS` → `Login with a web browser`，浏览器里输入一次性代码即可。
（也可以不用 gh，直接用 HTTPS 推送，届时会要求输入用户名和 **Personal Access Token**；**不要在对话里把 Token 发给我**。）

---

## 2.5 本次已确认的上传配置

| 项 | 值 |
|---|---|
| 仓库名 | **gongyibao-safety-risk-identifier** |
| 可见性 | ⚠️ **Public 公开**（你自己选的；想改成私有把下面命令的 `--public` 换成 `--private` 即可） |
| 内容 | 系统代码 + 7 个演示工艺包（放在 `示例数据/`）+ 机器人选型图 |
| 不上传 | `.venv`、`config.json`、`发布/`、`__pycache__` |

> ⚠️ **公开仓库特别提醒**：本项目示例数据涉及发射药/起爆药/雷管等军品相邻工艺。
> 虽已全部脱敏虚构、仅基于公开发布的行业通用常识，但公开到互联网仍请自行评估合规性；
> 若所在单位/导师有保密要求，建议直接使用 `--private`。切换命令：`gh repo edit --visibility private`。

---

## 3. 提交代码（可让我来做，也可以你自己跑）

```powershell
Set-Location "<解压后的目录>\安全风险辨识系统"    # 例：e:\桌面\工艺包\安全风险辨识系统

git init
git add .
git status                     # ← 关键：确认列表里【没有】config.json、.venv、发布/
git commit -m "feat: 工艺包安全风险辨识系统 v0.3.1-demo（规则引擎 + 多页报告 + 机器人/流程/故障树）"
git branch -M main
```

### ⚠️ 提交前必须核对

```powershell
git status --short | Select-String "config.json"     # 应输出为空
git ls-files | Select-String "config.json"           # 应输出为空
```

若发现 `config.json` 已被暂存，执行：`git rm --cached config.json`

---

## 4. 创建远程仓库并推送

**用 gh（一条命令搞定）：**

```powershell
gh repo create gongyibao-safety-risk-identifier --public --source=. --remote=origin --push
```

改私有仓库把 `--public` 换 `--private`。

**不用 gh 的话：** 先在网页上新建空仓库 `gongyibao-safety-risk-identifier`（**不要**勾选 Add README / .gitignore），然后：

```powershell
git remote add origin https://github.com/<你的用户名>/gongyibao-safety-risk-identifier.git
git push -u origin main
```

---

## 5. 上传后立即自查

```powershell
gh repo view --web                                  # 浏览器打开仓库
```

在网页上确认：

- [ ] 文件列表里 **没有 `config.json`**
- [ ] 没有 `.venv/`、`__pycache__/`、`发布/`
- [ ] `config.example.json` 在（占位符版本，安全）
- [ ] README 正常显示

**若 API Key 曾不小心上传过：立刻去服务商后台作废并重新生成该 Key**（GitHub 历史记录难以彻底清除）。

---

## 6. 本次会包含 / 不包含的内容

**会包含（约 1 MB 以内）**

```
app/                    FastAPI 后端与辨识引擎（ingest/rules/robots/references/flow/fta/reportdoc/orchestrator）
static/                 原生前端（index.html / js / css）
data/演示样例_工艺包.md   内置演示数据
示例数据/               7 个演示工艺包（.md）+ robot_media/（机器人选型图 SVG+PNG）
docs/                   示例报告（docx/json）与截图素材
archive_batch.py        批量辨识 + 归档脚本
archive_results.py      单包辨识 + 归档脚本
build_usage_docx.py     使用说明 → Word
selftest.py             自检脚本
START.bat / run.bat     一键启动
requirements.txt        依赖清单
config.example.json     配置模板（无密钥）
README.md / CHANGELOG.md / VERSION / 使用说明.md / 使用说明.docx
.gitignore              敏感文件排除规则
上传到GitHub.md         本文件
```

**不包含**

```
.venv/                  Python 虚拟环境（45 MB）
config.json             ★ 含真实 API Key
发布/                   v0.3.0 旧发布包（2.9 MB）
__pycache__/            131 个缓存目录
```

**待你确认是否加入**

```
（已确认不加入）
```

---

## 7. 常见问题

- **`git push` 报拒绝**：仓库若已初始化过 README，先 `git pull --rebase origin main` 再 push。
- **中文文件名乱码**：执行 `git config --global core.quotepath false`。
- **提交后想改仓库可见性**：`gh repo edit --visibility public`（或 `private`）。
- **只想传代码不传文档**：把 `docs/`、`*.docx` 也加进 `.gitignore` 即可。
