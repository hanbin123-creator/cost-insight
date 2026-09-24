#!/bin/sh
# 容器启动闸：索引缺失时从挂卷的考题数据现场构建（幂等、离线）。
# 镜像不再内嵌 data/kb（赛题保密数据派生物不进构建上下文，评委 clone 即建）。
# 命名卷首次创建为空 → 三件套 + Milvus Lite 库全部现场构建；以后重启直接命中。
set -e
# 官方报告模板属赛题资源不入库：容器启动时从挂载的数据源复制（缺失则报告功能给友好报错）
if [ ! -f /app/assets/report_template.docx ] && [ -f "/data-source/04_报告模板/月度成本分析报告模板.docx" ]; then
    cp "/data-source/04_报告模板/月度成本分析报告模板.docx" /app/assets/report_template.docx
    echo "[entrypoint] 报告模板已从数据源就位"
fi
if [ ! -f /app/data/kb/chunks.jsonl ]; then
    echo "[entrypoint] 索引缺失，从 /data-source 现场构建（首次启动约 1-2 分钟）..."
    python -c "from app.kb import build_index; chunks = build_index(); print(f'[entrypoint] 索引构建完成：{len(chunks)} 块')"
fi
if [ "$VECTOR_BACKEND" = "milvus_lite" ] && [ ! -f /app/data/kb/milvus_lite.db ]; then
    echo "[entrypoint] 构建 Milvus Lite 向量库..."
    python -c "from app.kb import build_milvus_lite; n = build_milvus_lite(); print(f'[entrypoint] 写入 {n} 条向量')"
fi
exec uvicorn app.api:app --host 0.0.0.0 --port 8000
