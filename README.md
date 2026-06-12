# MicroSeg
MicroSeg started as an early personal project — a local PySide desktop tool that tangled UI, algorithms and threading into one Windows-only process. It was later **rebuilt and optimized with AI assistance** into a properly separated, browser-operated, fully async, one-command-deployable system with the same scientific capability.

**浏览器端的显微图像标注 · 模型训练 · 颗粒形态学 · 三维重建 · 孔隙渗透模拟工作台**
*A browser-based workbench for microscopic image annotation, model training, particle morphometry, 3D reconstruction & pore-network percolation.*

![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)
![Backend: FastAPI + Celery](https://img.shields.io/badge/backend-FastAPI%20%2B%20Celery-009688.svg)
![Frontend: Vue 3 + Three.js](https://img.shields.io/badge/frontend-Vue%203%20%2B%20Three.js-42b883.svg)
![Deploy: Docker Compose](https://img.shields.io/badge/deploy-Docker%20Compose-2496ed.svg)

[简体中文](#简体中文) · [English](#english)· [Preview](#Preview)

</div>

---

<a id="简体中文"></a>

## 简体中文

### 关于本项目

MicroSeg 的前身是一个早期的个人项目——一个本地的 PySide 桌面工具,把界面、算法和线程全揉在一个进程里,只能在 Windows 上单机运行。后来借助 AI 协助做了一次彻底重构与优化,把同样的科研能力拆成了**前后端分离、可浏览器操作、全异步、可一键部署**的形态。

> 这是一份个人项目的重构版本,代码与文档在 AI 协助下完成优化。欢迎学习、研究、二次开发——但请遵守下方的开源协议(非商业使用 + 相同方式共享)。

### 功能特性

- **交互式分割**——涂抹前景/背景,基于多尺度特征栈(高斯、Sobel、DoG、Hessian、结构张量、邻域)训练 LightGBM 像素分类器,一笔涂抹即可标注整帧(ilastik 风格,搬到了 HTTP 上)。
- **深度学习训练**——分割用 U-Net + EfficientNet 编码器 + scSE 注意力(\`segmentation-models-pytorch\`),检测用 YOLOv8。训练在独立 worker 进程中进行,实时回报每个 epoch 的进度与最佳验证 Dice。
- **颗粒形态学**——分水岭分割 + 逐对象的面积、等效直径、周长、粗糙度、圆度、伸长率、Feret 直径等(SimpleITK),可导出 CSV。
- **三维重建**——把 Z 序列堆成体数据,用 marching cubes 抽等值面,浏览器内用 Three.js 拖拽旋转查看。
- **渗透模拟**——把某一标签当作孔隙空间,运行侵入式渗透(invasion percolation),逐帧观察流体沿最宽喉道推进直至突破,附实时饱和度曲线、孔隙率与连通簇分析。
- **全异步**——每个长任务立刻返回 \`task_id\`,通过 WebSocket 实时推送进度,支持协作式取消,刷新浏览器也不丢任务。

### 采用技术

| 层                | 技术                                                         |
| ----------------- | ------------------------------------------------------------ |
| 后端框架          | FastAPI(async)· Python 3.12                                  |
| 任务队列          | Celery 5 + Redis(broker / result / 事件 pub-sub)             |
| 经典视觉/科学计算 | NumPy · SciPy · scikit-image · scikit-learn · **LightGBM** · **SimpleITK** |
| 深度学习(可选)    | PyTorch · **segmentation-models-pytorch** · **ultralytics (YOLOv8)** · albumentations |
| 前端              | Vue 3 · Vite 6 · Pinia · Vue Router                          |
| 可视化            | **Three.js**(三维等值面)· Canvas(渗透动画 / 标注画布)        |
| 部署              | Docker · Docker Compose · nginx                              |

### 架构概览

\`\`\`
                    ┌─────────────┐      WebSocket(任务事件)
   浏览器 ◄──────────┤   nginx     ├──────────────────────────────┐
   Vue 3 SPA        │ (frontend)  │                              │
        │ REST /api └──────┬──────┘                              │
        ▼                  ▼ 代理                                 │
   ┌──────────────────────────────┐   入队     ┌─────────────────┴──┐
   │           FastAPI            ├──────────►│      Redis         │
   │ projects · jobs · tasks · ws │           │ broker · 事件 · 记录 │
   └──────────────────────────────┘◄──────────┤                    │
                                     发布事件   └─────────┬──────────┘
                                                          │ 消费
                                                ┌─────────▼──────────┐
                                                │   Celery worker    │
                                                │ 分割/形态/渗透     │
                                                │ 网格/训练/推理     │
                                                └────────────────────┘
\`\`\`

设计原则:**API 永不阻塞**,所有重活都丢到 worker 进程,通过 Redis 回报进度。

### 快速开始(Docker)

\`\`\`bash
cp .env.example .env
docker compose up -d --build      # 启动 redis + api + worker + frontend(CPU)

# 打开 http://localhost:8080

\`\`\`

需要 GPU 训练/推理(需 NVIDIA Container Toolkit;Windows 走 WSL2):

\`\`\`bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
\`\`\`

停止:\`docker compose down\`(加 \`-v\` 会一并删除数据卷)。

> **Windows 用户**:用 Docker Desktop(WSL2 backend)即可,无需单独装 compose。\`make\` 在 Windows 默认没有,直接用上面的 \`docker compose\` 命令;若想用 Makefile 快捷方式,\`scoop install make\` 或 \`choco install make\`。

### 本地开发

\`\`\`bash

# 后端(需本地 redis 监听 6379)

cd backend
pip install -r requirements.txt && pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
celery -A app.workers.celery_app.celery_app worker --loglevel=info

# 前端

cd frontend
npm install && npm run dev        # http://localhost:5173
\`\`\`

深度学习训练/推理另需 ML 依赖:\`pip install -r requirements-ml.txt\`。纯 CPU 环境下这些任务仍会入队,等具备 torch 的 worker 时执行。

测试:\`cd backend && python -m pytest -q\`。

### 项目结构

\`\`\`
microseg/
├── backend/         FastAPI + Celery
│   └── app/
│       ├── api/     REST + WebSocket 路由
│       ├── core/    项目存储 + Redis 任务追踪
│       ├── ml/      特征/交互分割/形态学/渗透/体数据/训练/推理
│       ├── workers/ Celery 任务
│       └── main.py
├── frontend/        Vue 3 SPA(标注画布 / 任务监视 / 3D / 渗透动画)
├── deploy/nginx/    生产 nginx 配置
├── docs/            架构 / API / 迁移说明
├── docker-compose.yml       CPU 栈
└── docker-compose.gpu.yml   GPU 叠加层
\`\`\`

### 开源协议

本项目采用 **[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International（CC BY-NC-SA 4.0）](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh-hans)**,核心精神:

- **署名(BY)**——使用/修改时需注明原作者与出处。
- **非商业性使用(NC)**——不得用于商业目的。
- **相同方式共享(SA / 强制开源)**——基于本项目的修改与衍生作品,必须以**相同的协议**继续开放。

> ⚠️ **请注意(非法律意见)**:严格来说,"非商用"限制使本项目**不符合 OSI 对"开源"的定义**(开源定义不允许限制商业使用),准确的说法是 **source-available(源代码公开)**。此外,Creative Commons 官方**不建议将 CC 协议用于软件**(它未处理专利授权、也未区分源码与二进制)。如果你日后需要更贴合软件场景的方案,可考虑:**PolyForm Noncommercial 1.0.0**(专为非商用设计,copyleft 较弱)或 **AGPL-3.0 + Commons Clause**(强 copyleft + 禁止销售)。许可选择涉及法律后果,重大决定建议咨询专业法律意见。

完整法律文本见 [\`LICENSE\`](LICENSE) 或 CC 官方页面。

### 致谢与声明

前身为个人早期项目,现版本在 AI 协助下完成重构与优化。按现状(AS IS)提供,不附带任何明示或默示担保。

---

<a id="english"></a>

## English

### About

MicroSeg started as an early personal project — a local PySide desktop tool that tangled UI, algorithms and threading into one Windows-only process. It was later **rebuilt and optimized with AI assistance** into a properly separated, browser-operated, fully async, one-command-deployable system with the same scientific capability.

> This is the refactored version of a personal project; code and docs were optimized with AI assistance. You're welcome to study, research and build on it — under the license below (non-commercial + share-alike).

### Features

- **Interactive segmentation** — scribble foreground/background and a LightGBM pixel classifier trained on a multi-scale feature stack (Gaussian, Sobel, DoG, Hessian, structure tensor, neighborhood) labels the whole frame. The ilastik-style workflow, served over HTTP.
- **Deep-learning training** — U-Net with an EfficientNet encoder + scSE attention (\`segmentation-models-pytorch\`) for segmentation, YOLOv8 for detection. Training runs out-of-process and streams epoch progress and best validation Dice.
- **Particle morphometry** — watershed splitting plus per-object area, equivalent diameter, perimeter, rugosity, roundness, elongation, Feret diameter and more (SimpleITK), CSV-exportable.
- **3D reconstruction** — stack a Z-series into a volume, extract an isosurface with marching cubes, orbit it in the browser with Three.js.
- **Percolation simulation** — treat one label as pore space and run invasion percolation; watch the front advance through the widest throats and break through, with a live saturation curve, porosity and spanning-cluster analysis.
- **Async everything** — every long job returns a task id immediately and streams progress over a WebSocket, with cooperative cancellation; jobs survive a browser refresh.

### Tech stack

| Layer                    | Tech                                                         |
| ------------------------ | ------------------------------------------------------------ |
| Backend                  | FastAPI (async) · Python 3.12                                |
| Task queue               | Celery 5 + Redis (broker / result / event pub-sub)           |
| Classic CV / scientific  | NumPy · SciPy · scikit-image · scikit-learn · **LightGBM** · **SimpleITK** |
| Deep learning (optional) | PyTorch · **segmentation-models-pytorch** · **ultralytics (YOLOv8)** · albumentations |
| Frontend                 | Vue 3 · Vite 6 · Pinia · Vue Router                          |
| Visualization            | **Three.js** (3D isosurface) · Canvas (percolation animation / annotation) |
| Deploy                   | Docker · Docker Compose · nginx                              |

### Architecture

\`\`\`
                    ┌─────────────┐      WebSocket (task events)
   Browser ◄────────┤   nginx     ├──────────────────────────────┐
   Vue 3 SPA        │ (frontend)  │                              │
        │ REST /api └──────┬──────┘                              │
        ▼                  ▼ proxy                                │
   ┌──────────────────────────────┐   enqueue  ┌─────────────────┴──┐
   │           FastAPI            ├──────────►│      Redis         │
   │ projects · jobs · tasks · ws │           │ broker · events    │
   └──────────────────────────────┘◄──────────┤ task records       │
                                     publish    └─────────┬──────────┘
                                                          │ consume
                                                ┌─────────▼──────────┐
                                                │   Celery worker    │
                                                │ segment/morph/perc │
                                                │ mesh/train/infer   │
                                                └────────────────────┘
\`\`\`

Guiding principle: **the API never blocks** — everything heavy runs in the worker and reports back through Redis.

### Quick start (Docker)

\`\`\`bash
cp .env.example .env
docker compose up -d --build      # redis + api + worker + frontend (CPU)

# open http://localhost:8080

\`\`\`

GPU training/inference (needs the NVIDIA Container Toolkit; on Windows via WSL2):

\`\`\`bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
\`\`\`

Stop with \`docker compose down\` (add \`-v\` to also drop the data volumes).

> **Windows users**: Docker Desktop (WSL2 backend) ships \`docker compose\` — no separate install. \`make\` isn't present by default; use the \`docker compose\` commands above, or \`scoop install make\` / \`choco install make\` to use the Makefile shortcuts.

### Local development

\`\`\`bash

# backend (needs a local redis on :6379)

cd backend
pip install -r requirements.txt && pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
celery -A app.workers.celery_app.celery_app worker --loglevel=info

# frontend

cd frontend
npm install && npm run dev        # http://localhost:5173
\`\`\`

Deep-learning jobs additionally need \`pip install -r requirements-ml.txt\`. On a CPU-only host they still enqueue and run once a torch-capable worker is available.

Tests: \`cd backend && python -m pytest -q\`.

### License

This project is licensed under **[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)](https://creativecommons.org/licenses/by-nc-sa/4.0/)**:

- **Attribution (BY)** — credit the original author.
- **NonCommercial (NC)** — no commercial use.
- **ShareAlike (SA / copyleft)** — derivatives must be released under the **same** license.

> ⚠️ **Note (not legal advice)**: the non-commercial restriction means this is technically **source-available**, not "open source" under the OSI definition (which forbids restrictions on commercial use). Creative Commons also **advises against using CC licenses for software** (they don't address patents or distinguish source from object code). Software-oriented alternatives if you need them: **PolyForm Noncommercial 1.0.0** (non-commercial, weaker copyleft) or **AGPL-3.0 + Commons Clause** (strong copyleft + no resale). Licensing has legal consequences — consult a professional for important decisions.

Full legal text in [\`LICENSE\`](LICENSE) or on the official CC page.

### Acknowledgements

Originally a personal early-stage project; this version was refactored and optimized with AI assistance. Provided AS IS, without warranty of any kind.

### Preview
Here is some example, not for showing the accuracy, it is just the presenting how it works
## Annotation
<img width="2259" height="1200" alt="image" src="https://github.com/user-attachments/assets/5d130f82-749e-4974-9b45-ab35158408ef" />
## Analysis
<img width="2020" height="1203" alt="image" src="https://github.com/user-attachments/assets/0a46950b-1bd2-48a9-9839-05db8a864bde" />
<img width="2020" height="1203" alt="image" src="https://github.com/user-attachments/assets/c7deccea-1f94-4ab5-84c2-21a305da1245" />





