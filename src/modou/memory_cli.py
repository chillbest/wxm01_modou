"""Parse an explicit note manifest using test-only memory and a shared AI cache."""
from .logging_setup import note_statistics, note_phase, note_total, NoteStatistics, logged_main, event, context, summary

import argparse
import json
import time
from datetime import date
from pathlib import Path

from .catalog_memory import read_test_catalog
from .deepseek import CachedSuggestions, DeepSeek
from .local_config import read_config
from .parsing import parse_note, read_note


def run(manifest, output_dir, *, values, use_ai=False):
    rows = json.loads(manifest.read_text(encoding="utf-8-sig"))
    # Read and validate all local inputs before touching DB or calling AI.
    inputs = []
    for row in rows:
        path = manifest.parent / row['path']
        stats = NoteStatistics(path, shared=True)
        with context(note_id=str(path)):
            try:
                text = read_note(path)
                published = date.fromisoformat(row['date'])
            except BaseException as exc:
                stats.charge()
                stats.emit(exc)
                raise
        stats.charge()
        inputs.append((row, text, published, stats))
    if not inputs:
        raise ValueError("笔记清单不能为空")
    if output_dir.exists():
        raise ValueError("输出目录已存在，拒绝覆盖")
    prepared = time.monotonic()
    catalog = read_test_catalog(values)
    suggest = CachedSuggestions(DeepSeek(api_key=values.get("DEEPSEEK_API_KEY"),
                                        model=values.get("DEEPSEEK_MODEL"))) if use_ai else None
    event("批次共享准备", elapsed_seconds=round(time.monotonic() - prepared, 3))
    output_dir.mkdir(parents=True, exist_ok=False)
    summary = {"database": "modou_test", "alias_rows": len(catalog), "review_status": "pending", "notes": []}
    report = ["# M02数据库记忆核对表", "", "仅modou_test；所有结果待人工确认，未写业务表。史低备注不写数据库。", ""]
    for index, (row, text, published, stats) in enumerate(inputs, 1):
        with note_statistics(manifest.parent / row["path"], shared=True, existing=stats):
            result = parse_note(text, published_date=published, source_url=row.get("source_url"),
                                catalog=catalog, suggest=suggest, note_id=manifest.parent / row["path"])
            with note_phase("输出"):
                (output_dir / f"note-{index}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
                summary["notes"].append({"input": row["path"], "output": f"note-{index}.json", "items": len(result.items),
                                         "alias_hits": sum(i.match_status == "alias" for i in result.items),
                                         "ai_suggestions": sum(i.ai_suggestion is not None for i in result.items),
                                         "validation_errors": result.validation_errors})
                report += [f"## {result.title}", "", "| 行 | 原名 | 匹配状态 | 记忆名称/平台/版本 | AI名称/版本建议 | 地区 | 最终价 | 优惠方式 | 日期 | 备注 | 待确认 |",
                           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
                for item in result.items:
                    ai = item.ai_suggestion
                    fields = [item.line_number, item.raw_name, item.match_status,
                              "/".join(v or "待确认" for v in [item.name_zh, item.platform, item.edition]),
                              "/".join(v or "待确认" for v in [ai.name_zh, ai.edition]) if ai else "—",
                              item.region, item.lowprice_cny, item.lowprice_method, item.lowprice_date,
                              "；".join(item.notes) or "—", "；".join(item.issues) or "仅待人工确认"]
                    report.append("| " + " | ".join(str(v if v is not None else "待确认").replace("|", "/").replace("\n", " ") for v in fields) + " |")
                report.append("")
                print(f"笔记{index}完成：{len(result.items)}条；累计AI请求{suggest.requests if suggest else 0}次", flush=True)
    output_started = time.monotonic()
    summary["ai"] = suggest.stats() if suggest else {"requests": 0, "cache_hits": 0, "failures": 0}
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "review.md").write_text("\n".join(report), encoding="utf-8")
    event("审核文件生成", path=str(output_dir), count=len(inputs), shared_output_seconds=round(time.monotonic() - output_started, 3))
    return summary


@logged_main
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="JSON数组，path相对清单目录，date必填，source_url可选")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--deepseek", action="store_true")
    args = parser.parse_args()
    event("输入", input=str(getattr(args, "input", getattr(args, "manifest", "-"))))
    try:
        summary = run(args.manifest, args.output_dir, values=read_config(args.env_file), use_ai=args.deepseek)
    except Exception:
        parser.exit(1, "执行失败：请检查输入、测试库或API配置；未输出凭证，未写业务表。\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
