"""精排对照实验（证据脚本）：纯 RRF / 规则精排 / 神经精排 base / large / 集成，50 条评估集口径。

三路同口径：候选均取 RRF 融合前 10 名（与 RERANK_WINDOW 一致），只换精排器。
用法：python scripts/rerank_compare.py（--large-only 只跑 large；模型获取见 README「可选神经精排」）
"""
import os, sys
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rerank import RERANK_WINDOW
from scripts.eval_retrieval import EVAL_CASES, _get_retriever

def metric(ranked_hits_per_query):
    rr, top1, top5 = 0.0, 0, 0
    for (q, t), hits in ranked_hits_per_query.items():
        rank = next((i + 1 for i, h in enumerate(hits[:5]) if t in h.doc_name), None)
        rr += 1.0 / rank if rank else 0.0
        top1 += rank == 1
        top5 += rank is not None
    n = len(ranked_hits_per_query)
    return rr / n, top1, top5, n

def main():
    only_large = "--large-only" in sys.argv
    r = _get_retriever()
    raw = {c: r.search(c[0], top_k=RERANK_WINDOW, rerank=False).hits for c in EVAL_CASES}
    ruled = {c: r.search(c[0], top_k=RERANK_WINDOW, rerank=True).hits for c in EVAL_CASES}

    if not only_large:
        for name, data in [("纯 RRF（无精排）", raw), ("规则精排（现况基线）", ruled)]:
            mrr, t1, t5, n = metric(data)
            print(f"{name}: MRR={mrr:.4f} Top1={t1}/{n} Top5={t5}/{n}")

    def run_ce(label, model_path, tok_path):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(str(tok_path))
        tok.enable_truncation(max_length=512)
        tok.enable_padding()
        sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        input_names = {i.name for i in sess.get_inputs()}

        def ce_score(q, texts):
            enc = tok.encode_batch([(q, t) for t in texts])
            feed = {"input_ids": [e.ids for e in enc],
                    "attention_mask": [e.attention_mask for e in enc]}
            if "token_type_ids" in input_names:
                feed["token_type_ids"] = [e.type_ids for e in enc]
            import numpy as np
            feed = {k: np.array(v, dtype=np.int64) for k, v in feed.items()}
            return sess.run(None, feed)[0].reshape(-1)

        out = {}
        for i, ((q, t), hits) in enumerate(raw.items()):
            scores = ce_score(q, [h.text for h in hits])
            out[(q, t)] = [h for h, _s in sorted(zip(hits, scores), key=lambda x: x[1], reverse=True)]
            print(f"  [{label}] {i+1}/{len(raw)}", flush=True)
        mrr, t1, t5, n = metric(out)
        print(f"{label}: MRR={mrr:.4f} Top1={t1}/{n} Top5={t5}/{n}")
        return out

    if not only_large:
        print("加载 bge-reranker-base（onnxruntime 直读 models/reranker/raw）……", flush=True)
        snap = next(Path("models/reranker/models--BAAI--bge-reranker-base/snapshots").iterdir())
        neural = run_ce("神经精排 bge-reranker-base", "models/reranker/raw/model.onnx", snap / "tokenizer.json")

    print("加载 bge-reranker-large（models/reranker/large）……", flush=True)
    neural_l = run_ce("神经精排 bge-reranker-large", "models/reranker/large/model.onnx", "models/reranker/large/tokenizer.json")

    if only_large:
        # 只看 large 相对现况基线的 Top1 变化
        print("\nTop1 变化明细（vs 规则精排基线）：", flush=True)
        for c in EVAL_CASES:
            b = ruled[c][0].doc_name if ruled[c] else None
            nn = neural_l[c][0].doc_name if neural_l[c] else None
            ok_b, ok_n = c[1] in (b or ""), c[1] in (nn or "")
            if ok_b != ok_n:
                print(f"  {'✚修正' if ok_n else '✖退错'} {c[0]} → {nn}", flush=True)
        return

    # 集成：神经序与规则序再做一次 RRF 融合（k=60，与主检索同机制）
    blended = {}
    for c in EVAL_CASES:
        rule_order = ruled[c]
        neural_rank = {h.text: i for i, h in enumerate(neural[c])}
        rule_rank = {h.text: i for i, h in enumerate(rule_order)}
        fused = sorted(rule_order,
                       key=lambda h: 1/(60+neural_rank.get(h.text, 99)) + 1/(60+rule_rank[h.text]),
                       reverse=True)
        blended[c] = fused
    mrr, t1, t5, n = metric(blended)
    print(f"集成精排（神经+规则 RRF 融合）: MRR={mrr:.4f} Top1={t1}/{n} Top5={t5}/{n}")

    # 逐条看神经精排改对了哪些、改错了哪些
    base_top1 = {c: (ruled[c][0].doc_name if ruled[c] else None) for c in EVAL_CASES}
    print("\nTop1 变化明细：")
    for c in EVAL_CASES:
        b, nn = base_top1[c], (neural[c][0].doc_name if neural[c] else None)
        ok_b, ok_n = c[1] in (b or ""), c[1] in (nn or "")
        if ok_b != ok_n:
            print(f"  {'✚修正' if ok_n else '✖退错'} {c[0]} → {nn}")

if __name__ == "__main__":
    main()
