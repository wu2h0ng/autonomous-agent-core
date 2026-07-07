# Frontend F1 — AI Native Business Data Agent OS

Next.js 14 + TypeScript + Tailwind CSS 前端应用。

## 快速开始

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build

# 运行测试
npm run lint
```

## 环境变量

复制 `.env.local` 并配置：

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_RUN_KEY=development-key
```

## 架构

- **API Client**: `src/lib/api.ts` — 封装 OS Core API 调用
- **State Management**: `src/lib/store.ts` — Zustand 全局状态
- **Pages**: 
  - `/` — 查询页面（自然语言输入 → EvidenceChain）
  - `/trace/[id]` — Trace 详情页面（待实现）
  - `/knowledge` — 知识资产目录（待实现）

## 依赖

- Next.js 14 (App Router)
- TypeScript
- Tailwind CSS
- @tanstack/react-query (API 状态管理)
- zustand (UI 状态管理)
- recharts (图表渲染)

## 开发状态

Phase 0 F1 工作区已实现：
- ✅ OpenAPI 类型生成 (`src/lib/api/schema.d.ts`)
- ✅ 查询页面 (`/`)
- ✅ Trace 查询与详情页面 (`/trace`、`/trace/[traceId]`)
- ✅ Knowledge 资产目录与详情页面 (`/knowledge`、`/knowledge/[assetId]`)
- ✅ Dashboard、EvidenceCards、ActionProposal、GovernancePanel、FeedbackBar 组件
- ⏳ Approval 工作流页面
- ⏳ E2E 测试 (Playwright)
