"""Exercise the real import pipeline in an isolated directory, without Telegram.

Local rendering is the default. --run-ai sends this document to DeepSeek and
incurs API usage. Never points at the production database.
"""

import argparse
import asyncio
import json
import shutil
import uuid
from pathlib import Path

import config
from scripts.database.db import init_db
from services.import_service import prepare_pages, process_import
from services.platform_service import create_import, get_import


async def run(source, output, run_ai):
    output.mkdir(parents=True, exist_ok=True)
    config.DB_PATH = str(output / "import.sqlite3")
    config.MEDIA_PATH = str(output / "media")
    Path(config.MEDIA_PATH).mkdir(exist_ok=True)
    await init_db()
    content = source.read_bytes()
    pdf = content.startswith(b"%PDF-")
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise ValueError("Document exceeds 20 MB")
    asset_id = uuid.uuid4().hex
    filename = asset_id + (".pdf" if pdf else ".jpg")
    if pdf:
        shutil.copyfile(source, Path(config.MEDIA_PATH) / filename)
    else:
        from services.import_service import normalize_image
        await asyncio.to_thread(normalize_image, source, Path(config.MEDIA_PATH) / filename)
    import_id = await create_import(1, source.stem, [{"id": asset_id, "filename": filename,
                                    "mime": "application/pdf" if pdf else "image/jpeg", "original_name": source.name}])
    pages = await prepare_pages(import_id)
    print(f"Rendered {len(pages)} pages; {sum(len(p['text_content']) for p in pages)} native text characters.", flush=True)
    if run_ai:
        await process_import(import_id)
        record = await get_import(import_id, 1)
        draft = output / "draft.json"
        draft.write_text(json.dumps(record["document"], ensure_ascii=False, indent=2), encoding="utf-8")
        questions = record["document"]["questions"]
        print(f"Draft saved: {draft}; questions={len(questions)}; open={sum(q['kind'] == 'open' for q in questions)}", flush=True)
    else:
        print("Local rendering complete. Add --run-ai to extract with DeepSeek.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--run-ai", action="store_true")
    args = parser.parse_args()
    if args.output_dir.resolve() == Path(config.DB_PATH).resolve().parent:
        parser.error("Choose a separate scratch directory, not the live database directory")
    try:
        asyncio.run(run(args.source, args.output_dir.resolve(), args.run_ai))
    except Exception as error:
        from services.deepseek_client import AIUnavailable
        from services.platform_service import PlatformError
        detail = str(error) if isinstance(error, (AIUnavailable, PlatformError, ValueError)) else type(error).__name__
        parser.exit(1, f"Import failed: {detail}\n")


if __name__ == "__main__":
    main()
