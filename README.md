# Adaptive English Speaking Agent

一个可独立运行的自适应英语表达学习 Agent。系统将学习目标、表达掌握度、错因和练习会话作为长期状态，根据反馈自主决定下一轮学习内容，再调用 LLM 生成受约束的表达与练习。

> 当前版本聚焦文本交互，不包含语音识别或发音评测。

## 为什么这是 Agent

```text
学习画像 → 每日规划 → LLM 内容生成 → 互动练习 → 结果评估
    ↑                                                ↓
    └────── 间隔复习与掌握度记忆 ← 错因诊断 ←───────┘
```

系统不只是调用一次模型：

- **长期记忆**：持久化表达级掌握度、连续答对次数、错因和下次复习日期。
- **自主规划**：根据最近 5 次会话正确率动态分配新学与复习内容。
- **工具执行**：调用 OpenAI 兼容接口生成自然表达和四类互动题。
- **反馈闭环**：练习结果更新长期状态，并立即影响下一轮题型和复习优先级。
- **可解释决策**：前端展示今日计划、规划理由、薄弱项和近期正确率。

## 技术设计

- Python / Flask
- OpenAI-compatible API（默认 DeepSeek）
- 确定性调度器 + LLM 内容生成
- JSON 本地持久化与原子替换写入
- 原生 HTML / CSS / JavaScript
- Python `unittest` + Node.js 回归测试

核心调度规则：

- 答对后的复习间隔：1、3、7、14、30 天。
- 答错后当天重新进入复习队列。
- 近期正确率 `< 60%` 时强化复习，`>= 85%` 时增加新表达。
- 按含义辨认、主动回忆、场景运用和表达配对四类错因调整题型比例。

## 项目结构

```text
backend/
  app.py                              # 独立 API 与静态页面服务
  generate_daily.py                   # 可交给任务计划运行的每日生成入口
  assistants/
    english_learning_agent.py         # 状态、调度、诊断与反馈
    english_assistant.py               # LLM 内容和练习生成工具
  tests/
frontend/
  index.html
  script.js
  style.css
docs/
  adaptive-english-agent-design.md
  engineering-learning-log.md
```

## 快速开始

要求 Python 3.10+。Node.js 仅用于运行前端测试。

```powershell
git clone https://github.com/NicholasZhao-zhenglin/adaptive-english-speaking-agent.git
cd adaptive-english-speaking-agent

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env
# 编辑 .env，填写 DEEPSEEK_API_KEY

python backend\app.py
```

浏览器打开 <http://127.0.0.1:5000>。Windows 也可以在创建虚拟环境后双击 `run.bat`。

首次运行时点击“生成今日内容”。如需用任务计划每天生成：

```powershell
.\.venv\Scripts\python.exe backend\generate_daily.py
```

## 配置

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DEEPSEEK_API_KEY` | OpenAI 兼容接口密钥 | 必填 |
| `DEEPSEEK_API_BASE` | API Base URL | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 模型名称 | `deepseek-chat` |
| `PORT` | Flask 监听端口 | `5000` |

`.env`、日志和 `backend/data/` 下的学习数据均被 Git 忽略。仓库不包含个人学习记录或 API Key。
服务固定监听 `127.0.0.1`，当前版本没有认证机制，不应直接暴露到公网或局域网。

## 测试

```powershell
cd backend
python -m unittest discover -s tests -v

cd ..\frontend
node tests\test_api_response.js
node tests\test_frontend_boundary.js
node --check api_response.js
node --check script.js
```

## 独立开发说明

本仓库从 [personal-assistant](https://github.com/NicholasZhao-zhenglin/personal-assistant) 中抽取英语学习模块，用于后续独立演进。原仓库中的对应代码仍然保留；两个项目不共享运行时数据或 Git 历史。

后续方向：

- 接入语音识别、发音和流利度评测；
- 用真实复习保持率校准掌握度公式和复习间隔；
- 增加生成质量离线评测集与可观测性；
- 多用户场景迁移到事务数据库并增加认证授权。
