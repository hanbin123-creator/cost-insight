# cost-insight · 制药企业产品成本智能分析系统

> 2026 年第二届重庆市 AI 大模型创新应用大赛 · 创灵境赛题
> 架构与选型依据见工作区《创灵境赛题_技术手册.md》（V2.0）及配套设计文档

## 结构

六大运行板块，一板块一文件；竞赛四模块 = 板块的场景组合（pipeline.py 预设表）。

```
app/
├── config.py    全部配置唯一出处（PROFILE 三档）
├── storage.py   存储层（SQLite→PostgreSQL 的唯一隔离点）
├── ingest.py    板块① 数据整理：CSV 加载→自洽校验→入库
├── compute.py   板块② 数据计算：全部数字的唯一产地
├── kb.py        板块①' 知识库（桩）
├── retrieve.py  板块③ 混合检索（桩）
├── generate.py  板块④ 智能生成（桩）
├── render.py    板块⑤ 渲染输出（桩）
├── act.py       板块⑥ 行动闭环（桩）
├── kg.py / predict.py / agent.py   加分项（桩）
├── llm.py / pipeline.py / context.py / schemas.py / main.py
tests/test_compute.py   板块①②对账测试（9 项，真实数据验证）
```

## 快速开始

```bash
pip install -r requirements.txt
# 数据包不入库（保密红线）。默认读取 ../创灵境_考题模拟数据，可用 CI_DATA_DIR 覆盖
python -m app.ingest            # 板块①：加载+校验+入库
python tests/test_compute.py    # 板块②：对账测试（无需 pytest 也可跑）
```

## 当前进度

- [x] 板块① 数据整理（加载即校验，5 条自洽规则）
- [x] 板块② 数据计算（环比/同比/预算偏差/贡献度/量差价差/对标三步法前两步/季度加权聚合/±10% 告警/看板 series/热力图 series）
- [ ] 板块③ 检索增强 ｜ [ ] 板块④ 智能生成 ｜ [ ] 板块⑤ 渲染输出 ｜ [ ] 板块⑥ 行动闭环
- [ ] 加分项：知识图谱 / 多模型 / Agent / 成本预测

## 关键口径备忘

- 对标差异率 = (一厂−二厂) ÷ 二厂（基期为二厂）
- 季度单位成本 = Σ总成本 ÷ Σ产量（加权，非算术平均）
- 量差价差借行情价反推单耗；行情表缺价的原料标注跳过
- 精度：计算全程 float64，仅输出层 ROUND_HALF_UP
