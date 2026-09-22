# -*- coding: utf-8 -*-
"""生成 placeholder-data/：公开仓库/CI 冒烟用的合成占位数据（非考题数据）。

保密红线：考题数据包不进公开仓库。本脚本生成的全部数值为合成值，
只保证三件事：①表头与考题数据包一致；②过 ingest 的全部硬校验
（单位成本=三要素之和 / 原材料占比=100% / 制造费用明细=汇总）；
③各端点有数据可渲染（CI 冒烟 + 评委无数据包时的界面预览）。

用法：python scripts/make_placeholder_data.py  →  写入 placeholder-data/
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "placeholder-data"
D1, D2 = "01_成本明细数据", "02_行业参考数据"

PRODUCTS = [("银黄口服液", "10ml×10支/盒"), ("板蓝根颗粒", "10g×20袋/盒"),
            ("六味地黄胶囊", "0.3g×60粒/盒")]
MONTHS_26 = [f"2026-{m:02d}" for m in range(1, 7)]
MONTHS_25 = [f"2025-{m:02d}" for m in range(1, 7)]


def _w(rel: str, header: list[str], rows: list[list]) -> None:
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8-sig") as f:   # BOM 对齐考题包
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _summary_rows(factory: str, months: list[str], markup: float) -> tuple[list, list, list, list]:
    """返回 summary / materials / overhead / labor 四组行；数值相互严格自洽。"""
    s_rows, m_rows, o_rows, l_rows = [], [], [], []
    for pi, (prod, spec) in enumerate(PRODUCTS):
        for mi, month in enumerate(months):
            mat = round((6.00 + 0.10 * pi + 0.05 * mi) * markup, 2)
            lab, ovh = round(2.00 * markup, 2), round(1.00 * markup, 2)
            unit = round(mat + lab + ovh, 2)          # 硬校验1：单位成本=三要素之和
            out = 10000 + 100 * mi + 1000 * pi
            total = round(out * unit, 2)              # 校验2：总成本=产量×单位成本
            s_rows.append([factory, prod, spec, month, out, mat, lab, ovh, unit, total])
            for herb, share in (("金银花", 0.6), ("黄芩", 0.4)):
                uc = round(mat * share, 2)            # 校验3：占比 60%+40%=100%
                m_rows.append([factory, prod, spec, month, out, herb, uc,
                               round(uc * out, 2), f"{int(share * 100)}%"])
            for cat, uc in (("折旧费", round(ovh * 0.6, 2)), ("水电费", round(ovh * 0.4, 2))):
                o_rows.append([factory, prod, spec, month, out, cat, uc, round(uc * out, 2)])
            # 校验4：明细 0.6+0.4=制造费用 1.00（ovh*0.6+ovh*0.4 二位小数下精确）
            labor_total = round(out * lab, 2)         # 校验5：派生单位人工=lab
            l_rows.append([factory, prod, spec, month, out, labor_total, 1000, 10, 20])
    return s_rows, m_rows, o_rows, l_rows


def main() -> None:
    sum_head = ["工厂", "产品名称", "产品规格", "月份", "产量(盒)", "直接材料(元/盒)",
                "直接人工(元/盒)", "制造费用(元/盒)", "单位成本(元/盒)", "总成本(元)"]
    mat_head = ["工厂", "产品名称", "产品规格", "月份", "产量(盒)", "原材料名称",
                "单位消耗成本(元/盒)", "原材料总成本(元)", "占总材料成本比例"]
    ovh_head = ["工厂", "产品名称", "产品规格", "月份", "产量(盒)", "费用类别",
                "单位费用(元/盒)", "费用总额(元)"]
    lab_head = ["工厂", "产品名称", "产品规格", "月份", "产量(盒)", "直接人工总额(元)",
                "总工时(小时)", "生产人数(人)", "工作天数(天)"]

    s26, m26, o26, l26 = _summary_rows("中药一厂", MONTHS_26, 1.00)
    s25, _, _, _ = _summary_rows("中药一厂", MONTHS_25, 0.97)
    b26, _, _, _ = _summary_rows("中药二厂", MONTHS_26, 1.10)
    b25, _, _, _ = _summary_rows("中药二厂", MONTHS_25, 1.07)

    _w(f"{D1}/中药一厂_成本汇总_2026年1-6月.csv", sum_head, s26)
    _w(f"{D1}/中药一厂_成本汇总_2025年1-6月.csv", sum_head, s25)
    _w(f"{D1}/中药二厂_成本汇总_2026年1-6月.csv", sum_head, b26)
    _w(f"{D1}/中药二厂_成本汇总_2025年1-6月.csv", sum_head, b25)
    _w(f"{D1}/中药一厂_原材料消耗明细_2026年1-6月.csv", mat_head, m26)
    _w(f"{D1}/中药一厂_制造费用明细_2026年1-6月.csv", ovh_head, o26)
    _w(f"{D1}/中药一厂_人工工时明细_2026年1-6月.csv", lab_head, l26)

    bud_head = ["工厂", "产品名称", "产品规格", "月份", "预算产量(盒)", "预算直接材料(元/盒)",
                "预算直接人工(元/盒)", "预算制造费用(元/盒)", "预算单位成本(元/盒)", "预算总成本(元)"]
    bud_rows = []
    for r in s26:
        factory, prod, spec, month, out, mat, lab, ovh, unit, _ = r
        b_out = out + 500
        bud_rows.append([factory, prod, spec, month, b_out, mat, lab, ovh, unit,
                         round(b_out * unit, 2)])
    _w(f"{D1}/中药一厂_预算数据_2026年.csv", bud_head, bud_rows)

    _w(f"{D2}/药材市场价格行情_2026年上半年.csv",
       ["药材名称", "规格等级", "单位", "1月价格", "2月价格", "3月价格", "4月价格",
        "5月价格", "6月价格", "价格来源", "趋势分析"],
       [["金银花", "统货", "元/kg", 100.0, 102.0, 101.0, 105.0, 108.0, 107.0,
         "合成占位", "合成数据，仅演示"],
        ["黄芩", "统货", "元/kg", 40.0, 41.0, 40.5, 42.0, 43.0, 42.5,
         "合成占位", "合成数据，仅演示"]])

    _w(f"{D2}/行业成本基准数据_2026.csv",
       ["产品类别", "指标", "行业P25", "行业P50", "行业P75", "本厂水平(中药一厂)", "对标评价"],
       [["口服液类", "材料成本占比", "50%", "55%", "60%", "56%", "合成占位评价"],
        ["口服液类", "人工成本占比", "15%", "18%", "22%", "19%", "合成占位评价"],
        ["口服液类", "制造费用占比", "8%", "10%", "13%", "9%", "合成占位评价"]])

    kb = ROOT / "03_制药知识文档"
    kb.mkdir(parents=True, exist_ok=True)
    (kb / "占位说明.txt").write_text(
        "本目录在公开仓库中仅为占位。考题知识文档属保密数据，请挂载真实数据包后使用。\n",
        encoding="utf-8")

    print(f"placeholder-data 生成完成：{ROOT}")


if __name__ == "__main__":
    main()
