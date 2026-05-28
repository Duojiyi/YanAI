<h1 align="center">颜AI</h1>


<p align="center">颜AI 是一个围绕 ChatGPT 图片能力封装的自托管图片创作与管理系统，提供 OpenAI 兼容图片 API、在线画图工作台、图生图预设、账号池轮询、个人用户额度、渠道管理、图片归档、日志与 Docker 部署能力。</p>

> [!WARNING]
> 免责声明：
>
> 本项目涉及对 ChatGPT 官网文本生成、图片生成与图片编辑等相关接口的逆向研究，仅供个人学习、技术研究与非商业性技术交流使用。
>
> - 严禁将本项目用于任何商业用途、盈利性使用、批量操作、自动化滥用或规模化调用。
> - 严禁将本项目用于破坏市场秩序、恶意竞争、套利倒卖、二次售卖相关服务，以及任何违反 OpenAI 服务条款或当地法律法规的行为。
> - 严禁将本项目用于生成、传播或协助生成违法、暴力、色情、未成年人相关内容，或用于诈骗、欺诈、骚扰等非法或不当用途。
> - 使用者应自行承担全部风险，包括但不限于账号被限制、临时封禁或永久封禁以及因违规使用等所导致的法律责任。
> - 使用本项目即视为你已充分理解并同意本免责声明全部内容；如因滥用、违规或违法使用造成任何后果，均由使用者自行承担。

> [!IMPORTANT]
> 本项目基于对 ChatGPT 官网相关能力的逆向研究实现，存在账号受限、临时封禁或永久封禁的风险。请勿使用你自己的重要账号、常用账号或高价值账号进行测试。

> [!CAUTION]
> 旧版本存在已知漏洞，请尽快升级到最新版本。公网部署时请尽量不要放置敏感信息，并自行做好访问控制与隔离。

## 快速开始

已发布镜像支持 `linux/amd64` 与 `linux/arm64`，在 x86 服务器和 Apple Silicon / ARM Linux 设备上都会自动拉取匹配架构的版本。

```bash
git clone git@github.com:huaiyuechusan/YanAI.git
cd YanAI
docker build -t your-registry/yanai:latest .
docker push your-registry/yanai:latest
```

当前仓库的 Docker 镜像不会包含 `config.json`、`data/`、`.env`、数据库文件或本地虚拟环境。服务器部署时请通过宿主机挂载提供运行时配置和数据：

```yaml
volumes:
  - ./data:/app/data
  - ./config.json:/app/config.json
```

服务器上准备配置和数据目录：

```bash
cp config.example.json config.json
# 编辑 config.json，将 auth-key 改成你自己的长随机密钥
mkdir -p data
YANAI_IMAGE=your-registry/yanai:latest docker compose up -d
```

也可以用环境变量 `CHATGPT2API_AUTH_KEY` 覆盖 `config.json` 中的 `auth-key`，但不要把真实密钥写进 Dockerfile、镜像构建参数或公开 compose 文件。

本地直接用当前代码启动容器可运行：

```bash
docker compose -f docker-compose.local.yml up -d --build
```

本地开发启动
```bash
cd D:\Desktop\颜AI
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000

cd D:\Desktop\颜AI\web
npm run dev
```

### 存储后端配置

支持通过环境变量 `STORAGE_BACKEND` 切换存储方式：

- `json` - 本地 JSON 文件（默认）
- `sqlite` - 本地 SQLite 数据库
- `postgres` - 外部 PostgreSQL（需配置 `DATABASE_URL`）
- `git` - Git 私有仓库（需配置 `GIT_REPO_URL` 和 `GIT_TOKEN`）

示例：使用 PostgreSQL
```yaml
environment:
  - STORAGE_BACKEND=postgres
  - DATABASE_URL=postgresql://user:password@host:5432/dbname
```

### 迁移前保护和审计

从旧 JSON 存储迁移到 SQLite、PostgreSQL 或 Git 前，必须先停写。Docker 部署请先停止 YanAI 容器，确认没有后台任务继续写入 `data/*.json`：

```bash
docker compose stop app
# 如果是按容器名直接管理，也可以使用：docker stop yanai
```

先执行只读审计，确认 8 类旧 JSON 数据的数量、重复主键、缺失主键和异常 JSON：

```bash
python scripts/audit_storage.py --data-dir data
```

生成完整 JSON 备份目录，并校验备份可恢复：

```bash
python scripts/backup_storage.py --data-dir data --backup-dir data/backups/pre-migration
python scripts/backup_storage.py --verify data/backups/pre-migration
```

恢复演练可以写到临时目录，避免覆盖生产数据：

```bash
python scripts/backup_storage.py --restore data/backups/pre-migration --target-dir .tmp/restore-check
python scripts/audit_storage.py --data-dir .tmp/restore-check --fail-on-issues
```

迁移脚本支持预演、迁移前备份和只校验模式：

```bash
python scripts/migrate_storage.py --from json --to postgres --dry-run
python scripts/migrate_storage.py --from json --to postgres --backup-dir data/backups/pre-postgres
python scripts/migrate_storage.py --from json --to postgres --verify-only
```

## 功能

### API 兼容能力

- 兼容 `POST /v1/images/generations` 图片生成接口
- 兼容 `POST /v1/images/edits` 图片编辑接口
- 管理员密钥可调用 `POST /v1/chat/completions`、`POST /v1/responses` 与 `POST /v1/messages`
- `GET /v1/models` 会返回上游模型列表，并补充内置图片模型 `gpt-image-2`、`codex-gpt-image-2`
- 图片接口支持 `n=1-4`，前端工作台会按张数拆分任务执行
- 支持内置账号池与 OpenAI 图片兼容外部渠道，按模型、权重、优先级进行路由
- 支持 Codex 中的画图接口逆向，仅 `Plus` / `Team` / `Pro` 订阅可用，模型别名为 `codex-gpt-image-2`，用于和官网画图区分

### 在线画图功能

- 内置「画图」工作台，支持文生图、图生图和多参考图编辑
- 提供眼镜搭配、发型报告、自然美颜、写真随机风格、照片增强、暗光修复、高清细节修复等预设提示词
- 支持参考图上传、粘贴图片、图片比例选择和多张任务队列
- 本地保存图片会话历史，支持回看、删除、清空和从结果图继续编辑
- 服务端可缓存生成图片，并在「图片管理 / 我的图片」中按日期筛选、预览和复制地址

### 号池管理功能

- 自动刷新账号邮箱、类型、额度和恢复时间
- 轮询可用账号执行图片生成与图片编辑
- 遇到 Token 失效类错误时自动剔除无效 Token
- 定时检查限流账号并自动刷新
- 支持网页端配置全局 HTTP / HTTPS / SOCKS5 / SOCKS5H 代理
- 支持搜索、筛选、批量刷新、导出、手动编辑和清理账号
- 支持四种导入方式：本地 CPA JSON 文件导入、远程 CPA 服务器导入、`sub2api` 服务器导入、`access_token` 导入
- 支持在设置页配置 `sub2api` 服务器，筛选并批量导入其中的 OpenAI OAuth 账号

### 管理台功能

- 管理员可创建个人用户、调整额度、禁用账号、重置密码
- 支持个人用户注册、登录、兑换码领取额度，以及个人图片记录查看
- 支持 OpenAI 图片兼容渠道管理，可设置 Base URL、API Key、模型、权重、优先级和超时时间
- 支持系统日志查看、图片访问地址配置、自动清理天数、账号刷新间隔和模型映射配置

### 注册机邮箱 Provider

注册机支持在 `/register` 页面配置多个临时邮箱 provider，并按启用顺序轮换。`moemail` 配置示例：

```json
{
  "enable": true,
  "type": "moemail",
  "api_base": "https://moemail.app",
  "api_key": "YOUR_MOEMAIL_API_KEY",
  "default_domain": "moemail.app",
  "expiry_time": 3600000
}
```

`api_base` 可以改为你自部署的 MoeMail 地址；`expiry_time` 单位为毫秒，`3600000` 表示 1 小时。

### 实验性 / 注意事项

- 文本类兼容接口主要面向管理员密钥和调试场景，个人用户仅开放图片相关能力
- 流式图片与文本输出仍建议谨慎测试
- 详细状态说明见：[功能清单](./docs/feature-status.en.md)

## 截图

### 画图功能
![image-20260528003118319](README.assets/image-20260528003118319.png)

### 用户管理
![image-20260527225749892](README.assets/image-20260527225749892.png)

### 账号池管理（添加RT的获取）
![image-20260527225645511](README.assets/image-20260527225645511.png)

### 注册机管理
![image-20260527225605667](README.assets/image-20260527225605667.png)

### 提示词管理
![image-20260527225454889](README.assets/image-20260527225454889.png)

### 图片管理

![image-20260527225445602](README.assets/image-20260527225445602.png)

### 渠道管理（在原有项目基础上添加第三方渠道）
![image-20260527225435590](README.assets/image-20260527225435590.png)

### 兑换码管理
![image-20260527225427154](README.assets/image-20260527225427154.png)

### 用户登录注册功能（添加L站登录和邮箱验证）
![image-20260527224931515](README.assets/image-20260527224931515.png)

## API

所有 AI 接口都需要请求头：

```http
Authorization: Bearer <auth-key>
```

<details>
<summary><code>GET /v1/models</code></summary>
<br>

返回上游模型列表，并补充当前内置图片模型。

```bash
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer <auth-key>"
```

<details>
<summary>说明</summary>
<br>

| 字段   | 说明                                                       |
|:-----|:---------------------------------------------------------|
| 返回模型 | 上游模型列表，并补充 `gpt-image-2`、`codex-gpt-image-2` 图片模型 |
| 接入场景 | 可接入 Cherry Studio、New API 等上游或客户端                        |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/images/generations</code></summary>
<br>

OpenAI 兼容图片生成接口，用于文生图。

```bash
curl http://localhost:8000/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "一只漂浮在太空里的猫",
    "n": 1,
    "response_format": "b64_json"
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段                | 说明                                                 |
|:------------------|:---------------------------------------------------|
| `model`           | 图片模型，当前可用值以 `/v1/models` 返回结果为准，推荐使用 `gpt-image-2` |
| `prompt`          | 图片生成提示词                                            |
| `n`               | 生成数量，当前后端限制为 `1-4`                                 |
| `response_format` | 当前请求模型中包含该字段，默认值为 `b64_json`                       |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/images/edits</code></summary>
<br>

OpenAI 兼容图片编辑接口，用于上传图片并生成编辑结果。

```bash
curl http://localhost:8000/v1/images/edits \
  -H "Authorization: Bearer <auth-key>" \
  -F "model=gpt-image-2" \
  -F "prompt=把这张图改成赛博朋克夜景风格" \
  -F "n=1" \
  -F "image=@./input.png"
```

<details>
<summary>字段说明</summary>
<br>

| 字段       | 说明                                  |
|:---------|:------------------------------------|
| `model`  | 图片模型， `gpt-image-2`                 |
| `prompt` | 图片编辑提示词                             |
| `n`      | 生成数量，当前后端限制为 `1-4`                  |
| `image`  | 需要编辑的图片文件，使用 multipart/form-data 上传 |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/chat/completions</code></summary>
<br>

面向图片场景的 Chat Completions 兼容接口，不是完整通用聊天代理。

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-image-2",
    "messages": [
      {
        "role": "user",
        "content": "生成一张雨夜东京街头的赛博朋克猫"
      }
    ],
    "n": 1
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段         | 说明                |
|:-----------|:------------------|
| `model`    | 图片模型，默认按图片生成场景处理  |
| `messages` | 消息数组，需要是图片相关请求内容  |
| `n`        | 生成数量，按当前实现解析为图片数量 |
| `stream`   | 已实现，但仍在测试         |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/responses</code></summary>
<br>

面向图片生成工具调用的 Responses API 兼容接口，不是完整通用 Responses API 代理。

```bash
curl http://localhost:8000/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-5",
    "input": "生成一张未来感城市天际线图片",
    "tools": [
      {
        "type": "image_generation"
      }
    ]
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段       | 说明                            |
|:---------|:------------------------------|
| `model`  | 响应中会回显该模型字段，但图片生成当前仍走图片生成兼容逻辑 |
| `input`  | 输入内容，需要能解析出图片生成提示词            |
| `tools`  | 必须包含 `image_generation` 工具请求  |
| `stream` | 已实现，但仍在测试                     |

<br>
</details>
</details>

## 社区支持

学 AI , 上 L 站：[LinuxDO](https://linux.do)

## 致谢

感谢佬友的 [basketikun/chatgpt2api](https://github.com/basketikun/chatgpt2api) 项目在 ChatGPT 逆向整理、OpenAI 兼容接口封装和自托管部署思路上的探索与开源分享。颜AI 的项目方向与部分实现思路受其启发。<br>
感谢佬友的[贴一个让设计师也觉得脊背发凉的提示词 ](https://linux.do/t/topic/532495)<br>
感谢佬友的 [🍌Banana Prompt Quicker](https://linux.do/t/topic/1244563)项目在提示词快捷工作流上的开源分享与启发。<br>

## Contributors

感谢所有为本项目做出贡献的开发者：

<a href="https://github.com/huaiyuechusan/YanAI/graphs/contributors">
  <img alt="Contributors" src="https://contrib.rocks/image?repo=huaiyuechusan/YanAI" />
</a>

## Star History

[![Star History Chart](https://api.star-history.com/chart?repos=huaiyuechusan/YanAI&type=date&legend=top-left)](https://www.star-history.com/?repos=huaiyuechusan%2FYanAI&type=date&legend=top-left)
