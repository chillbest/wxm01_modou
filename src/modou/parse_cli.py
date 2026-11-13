"""Parse one local note; creates a new review artifact without overwriting."""
import argparse
import json
from datetime import date
from pathlib import Path

from .parsing import CatalogEntry, parse_note, read_note


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--source-url")
    parser.add_argument("--catalog", type=Path, help="JSON数组：name_zh/name_en/aliases")
    parser.add_argument("--test-db", action="store_true", help="仅从modou_test读取game_alias")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--deepseek", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.test_db and args.catalog:
        parser.error("--test-db与--catalog不能同时使用")
    if args.output.exists():
        parser.error("输出文件已存在，拒绝覆盖")
    from .local_config import read_config
    values = read_config(args.env_file)
    catalog = [CatalogEntry.model_validate(row) for row in json.loads(
        args.catalog.read_text(encoding="utf-8-sig"))] if args.catalog else []
    if args.test_db:
        from .catalog_memory import read_test_catalog
        try:
            catalog = read_test_catalog(values)
        except Exception:
            parser.exit(1, "测试库目录读取失败；请检查配置与连接，凭证不输出。\n")
    suggest = None
    if args.deepseek:
        from .deepseek import CachedSuggestions, DeepSeek
        suggest = CachedSuggestions(DeepSeek(api_key=values.get("DEEPSEEK_API_KEY"),
                                            model=values.get("DEEPSEEK_MODEL")))
    result = parse_note(read_note(args.input),
                        published_date=args.date, source_url=args.source_url,
                        catalog=catalog, suggest=suggest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(result.model_dump_json(indent=2))
    print(f"候审条目：{len(result.items)}；含问题：{sum(bool(i.issues) for i in result.items)}")
    if suggest:
        print(f"AI调用统计：{suggest.stats()}")


if __name__ == "__main__":
    main()
