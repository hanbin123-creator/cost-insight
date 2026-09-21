"""全局配置：路径、常量、口径。所有配置唯一出处。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # cost-insight/
WORKSPACE = ROOT.parent                                 # 创灵境工作区


def _load_dotenv(path: Path) -> None:
    """stdlib 版 .env 加载（V1 修复）：逐行 KEY=VALUE，os.environ.setdefault。
    不覆盖已存在的环境变量（Docker/评测注入优先）；文件不存在静默跳过。
    零新依赖——python-dotenv 对一个文件来说是多余的。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

# 容器化挂点：compose 把考题数据挂到 /data-source 并用环境变量指过来（默认本机开发路径）
DATA_DIR = Path(os.environ.get("COST_INSIGHT_DATA_DIR",
                               WORKSPACE / "创灵境_考题模拟数据"))
DB_PATH = ROOT / "data" / "cost.db"

# 业务常量
ALERT_THRESHOLD = 0.10          # 波动告警阈值 ±10%（赛题 5.2.3）
MONEY_NDIGITS = 2               # 金额输出保留 2 位
PCT_NDIGITS = 1                 # 百分比输出保留 1 位

# 校验容差（CSV 为 2 位小数快照，存在四舍五入漂移，见测试记录）
TOL_UNIT_COST = 0.011           # 单位成本 = 材料+人工+制造费用
TOL_TOTAL_COST_RATIO = 0.0005   # 总成本 = 产量×单位成本 的相对误差
TOL_SHARE_SUM = 0.6             # 原材料占比合计 vs 100（百分点）
TOL_OVERHEAD = 0.021            # 制造费用明细合计 vs 汇总表（元/盒）

PRODUCTS = ["银黄口服液", "板蓝根颗粒", "六味地黄胶囊"]
FACTORY_MAIN = "中药一厂"
FACTORY_BENCH = "中药二厂"
COST_ELEMENTS = ["直接材料(元/盒)", "直接人工(元/盒)", "制造费用(元/盒)"]
ELEMENT_SHORT = {"直接材料(元/盒)": "直接材料", "直接人工(元/盒)": "直接人工", "制造费用(元/盒)": "制造费用"}

# ---- 列名常量（D2 整改：表头唯一出处，SQL/代码禁止散落字面量）----
COL_PRODUCT = "产品名称"
COL_MONTH = "月份"
COL_UNIT_COST = "单位成本(元/盒)"
COL_TOTAL_COST = "总成本(元)"
COL_OUTPUT = "产量(盒)"
COL_MAT_NAME = "原材料名称"
COL_MAT_UNIT_COST = "单位消耗成本(元/盒)"
COL_MAT_SHARE = "占总材料成本比例"
COL_OVERHEAD_UNIT = "单位费用(元/盒)"
COL_HERB = "药材名称"
COL_MKT_PRICE = "市场价"
# 人工工时明细
COL_LABOR_TOTAL = "直接人工总额(元)"
COL_LABOR_HOURS = "总工时(小时)"
COL_LABOR_HEADCOUNT = "生产人数(人)"
COL_LABOR_DAYS = "工作天数(天)"
COL_LABOR_UNIT_DERIVED = "单位人工成本(元/盒)"   # 派生列
# 预算表
BUDGET_COLS = {"直接材料": "预算直接材料(元/盒)", "直接人工": "预算直接人工(元/盒)",
               "制造费用": "预算制造费用(元/盒)", "单位成本": "预算单位成本(元/盒)"}
# 告警通道阈值（D6 三级口径）
ALERT_MATERIAL_MOM = 8.0        # 通道② 原材料环比 ±8%
ALERT_CUMULATIVE = 10.0         # 通道③ 行情累计涨幅 ±10%
YEAR_BASE_MONTH = "2026-01"     # 通道③ 累计口径基期

# ---- 板块③ 检索增强 ----
KB_DIR = DATA_DIR / "03_制药知识文档"
KB_INDEX_DIR = ROOT / "data" / "kb"          # 索引产物目录
CHUNK_SIZE = 500                             # 块上限（字）
CHUNK_OVERLAP = 50                           # 块间重叠（字）
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"       # ONNX 本地嵌入，512 维
MODEL_CACHE_DIR = ROOT / "models" / "fastembed"   # 项目内模型缓存（烘焙交付，D11）
MODEL_READY_MARKER = MODEL_CACHE_DIR / ".ready"   # 下载脚本验证通过后写入
VECTOR_BACKEND = os.environ.get("VECTOR_BACKEND", "numpy")  # numpy=dev 精确余弦 / milvus_lite=Docker 生产
RRF_K = 60                                   # RRF 融合常数（业界标准值）
TENANT = "中药一厂"                           # 演进友好字段：多租户第一天就带

# ---- 板块⑥ 行动闭环（RPA）----
# V2 修复：默认 127.0.0.1 而非 localhost——本机 Windows 上 Python 对 localhost
# 的每次 HTTP 调用被解析拖慢约 2 秒（127.0.0.1 仅 15ms），dispatch 三次调用慢 6 秒
RPA_BASE_URL = os.environ.get("RPA_BASE_URL", "http://127.0.0.1:8090")  # 官方 mock；评测零改码切换
RPA_TIMEOUT = 30.0                       # 官方接口文档超时约定（秒）
RPA_RETRY_BACKOFF = (2.0, 4.0)           # 指数退避序列（与 llm.py 同策略：3 次尝试）
RPA_ROSTER_PATH = ROOT / "config" / "rpa_assignees.yaml"   # 责任人名册（演示数据，YAML 外置）

# ---- Agent 意图路由（加分项 6.4）----
INTENT_CONFIDENCE_THRESHOLD = 0.7      # 低于此置信度 → 四入口卡片让用户选（不猜）
INTENT_LLM_TIMEOUT = 30.0              # 意图分类小模型超时（秒）
