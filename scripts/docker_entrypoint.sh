#!/bin/sh
# 容器启动闸：向量后端为 milvus_lite 且库文件缺失时现场构建（幂等）。
# 命名卷首次创建会把镜像内 data/kb 三件套（chunks/vectors/kg.json）复制进卷，
# 此处在其基础上补 Milvus Lite 库——以后重启直接命中，不重建。
set -e
if [ "$VECTOR_BACKEND" = "milvus_lite" ] && [ ! -f /app/data/kb/milvus_lite.db ]; then
    echo "[entrypoint] 构建 Milvus Lite 向量库..."
    python -c "from app.kb import build_milvus_lite; n = build_milvus_lite(); print(f'[entrypoint] 写入 {n} 条向量')"
fi
exec uvicorn app.api:app --host 0.0.0.0 --port 8000
