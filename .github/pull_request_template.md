## 变更摘要

<!-- 一句话:做了什么,属于哪个任务卡(PROJECT_PLAN T#)/阶段(ROADMAP P#) -->

- Track: Product / Research / Docs-Governance
- 用户/研究入口:
- Product Blueprint 条款:

## 产品与研究影响

- 产品能力:真实实现 / staged / 无（入口与 contract:____）
- 研究主张:1 利害 / 2 相关性 / 3 可纠正 / 4 器官非主体 / 其他____ / 无
- 机制变更:有(ADR 链接:____) / 无
- 是否跨 Research -> Product 晋升:是(`ResearchCandidateManifest`:____) / 否

## Research Track 证伪声明(涉及研究时必填)

- [ ] 本变更**未**为通过任何预注册门而调整机制参数或结构
- [ ] 若修改了实验:只动了实验有效性(环境/度量),同轮未动机制
- [ ] 负结果(如有)已如实记录于:____

## 质量门(粘贴输出)

```text
Research: PYTHONPATH=src python -m unittest discover -s tests
Product P0A unit: python3 -m pytest tests/product -q
Product P0A lint: ruff check packages/contracts/src packages/os_core/src tests/product
Product P0A types: pyright
Product P0A contracts wheel: uv build --wheel --out-dir /tmp/agent-os-product-wheel packages/contracts
Product P0A core wheel: uv build --wheel --out-dir /tmp/agent-os-product-wheel packages/os_core
Product P0A install smoke: clean venv imports agent_os_contracts + agent_os_core and cannot resolve aac/envs
Later Product packets: <integration/e2e/security commands from current product ADR/plan>
Output: <粘贴>
```

## 边界自查

- [ ] Research agent 代码路径无 `op_*` 调用;罩分离测试未删减
- [ ] Product Track 未直接 import Research Track 实验代码或结果文件
- [ ] 若涉及 Data Agent donor:任务为 SPINE-1，ADR-0054 G0/G1 已满足；任何 history
      import 前已绑定 full SHA、provenance 与 full-history safety `PASS`
- [ ] Product Track 无 donor/`_migration` runtime import；filtered history 的
      old-to-new commit map 已记录（如适用）
- [ ] OS core 无领域耦合;领域语义仅在 domain pack/plugin/connector
- [ ] model/plugin/subagent 无 untyped 最终执行权限
- [ ] secret/credential/tenant data 未进入 prompt、event、log 或模型可见 memory
- [ ] 产品主张、研究结果、内部流程已分开表述
- [ ] codebase_index.md 已更新(如有新模块/文档)
