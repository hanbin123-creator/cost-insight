# 第三方开源组件致谢与许可证（赛题 6.3 合规）

本项目代码为参赛团队原创。以下第三方开源组件被直接分发或引用，按赛题要求标注来源与许可证。

## 直接分发的二进制资源

| 组件 | 来源 | 许可证 | 用途 |
|---|---|---|---|
| Noto Sans SC 字体（Regular/Bold） | Google Fonts / Adobe（github.com/notofonts） | SIL Open Font License 1.1 | PDF 报告的中文字体嵌入（容器内安装） |
| bge-small-zh-v1.5 嵌入模型权重 | BAAI 智源（HuggingFace: BAAI/bge-small-zh-v1.5；经 Qdrant fastembed 分发） | MIT License | 知识库中文向量化（本地推理，离线可用） |

## 主要开源依赖（通过包管理器引用，详见 requirements.txt / web/package.json）

| 依赖 | 许可证 | 用途 |
|---|---|---|
| FastAPI / Uvicorn / Starlette | MIT / BSD | 后端 API 框架 |
| Pandas / NumPy | BSD-3 | 成本计算引擎 |
| python-docx / docxtpl | MIT / LGPL-2.1 | Word 报告渲染 |
| LibreOffice（容器内安装） | MPL-2.0 | docx → PDF 转换 |
| pypdfium2 | Apache-2.0 / BSD | PDF 页码定位与校验 |
| Milvus Lite / fastembed | Apache-2.0 / MIT | 向量检索（可选后端） |
| jieba | MIT | 中文分词（检索通道） |
| Vue 3 / Vite / ECharts | MIT / Apache-2.0 | 前端看板 |
| pytest / vitest | MIT | 测试 |

## 说明

- 上述组件的许可证原文见各组件官方仓库；Noto 字体与 bge 模型权重的许可证副本随二进制一同保留在本目录（assets/fonts/、models/）。
- 赛题官方资源（考题数据、报告模板、RPA mock 服务）**不属于开源组件**，按保密承诺不随本仓库分发。
