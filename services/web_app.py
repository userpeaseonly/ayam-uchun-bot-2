"""Same-origin aiohttp API and static Mini App hosting."""

import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web
from pydantic import ValidationError

import config
from scripts.database.db import get_db_connection
from services import platform_service as platform
from services.import_service import media_file
from services.upload_service import store_source, start_collection
from services.telegram_auth import verify_init_data, make_session, read_session

logger = logging.getLogger(__name__)
USER_KEY = web.RequestKey("identity", dict)
BOT_USERNAME_KEY = web.AppKey("bot_username", str)


@web.middleware
async def security(request, handler):
    try:
        if request.path.startswith("/api/"):
            if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("Origin"):
                configured = urlsplit(config.MINI_APP_URL)
                allowed = f"{configured.scheme}://{configured.netloc}" if configured.netloc else f"{request.scheme}://{request.host}"
                if request.headers["Origin"] != allowed:
                    raise platform.PlatformError("Noto'g'ri so'rov manbasi.", 403)
            if request.path != "/api/session":
                request[USER_KEY] = read_session(request.cookies.get("ayam_session", ""))
                if request.path.startswith("/api/admin/") and request[USER_KEY]["id"] not in config.ADMIN_IDS:
                    raise platform.PlatformError("Faqat o'qituvchilar uchun.", 403)
        response = await handler(request)
    except platform.PlatformError as error:
        response = web.json_response({"error": str(error)}, status=error.status)
    except (ValidationError, json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError, KeyError):
        message = "Ma'lumot tuzilmasi noto'g'ri. Savol va maydonlarni tekshiring."
        response = web.json_response({"error": message}, status=400)
    except web.HTTPException as error:
        if request.path.startswith("/api/"):
            response = web.json_response({"error": error.reason}, status=error.status)
        else:
            response = error
    except Exception:
        logger.exception("Mini App request failed: %s %s", request.method, request.path)
        response = web.json_response({"error": "Server xatosi. Qayta urinib ko'ring."}, status=500)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store" if request.path.startswith("/api/") else "no-cache"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'self'"
    return response


def user(request):
    return request[USER_KEY]


async def body(request):
    data = await request.json()
    if not isinstance(data, dict):
        raise platform.PlatformError("JSON obyekt kerak.")
    return data


async def session(request):
    data = await body(request)
    identity = verify_init_data(data.get("init_data"))
    response = web.json_response(identity_payload(request, identity))
    response.set_cookie("ayam_session", make_session(identity), httponly=True,
                        secure=config.MINI_APP_URL.startswith("https://"), samesite="Strict", max_age=12 * 3600, path="/")
    return response


async def me(request):
    return web.json_response(identity_payload(request, user(request)))


def identity_payload(request, identity):
    username = request.app.get(BOT_USERNAME_KEY)
    return {"user": identity, "is_admin": identity["id"] in config.ADMIN_IDS,
            "bot_import_url": f"https://t.me/{username}?start=import" if username else None}


async def imports(request):
    if request.method == "GET":
        return web.json_response(await platform.list_imports(user(request)["id"]))
    reader = await request.multipart()
    assets, total = [], 0
    paths = []
    committed = False
    try:
        async for part in reader:
            if part.name != "files" or not part.filename:
                raise platform.PlatformError("Fayllarni files maydonida yuboring.")
            if len(assets) >= config.MAX_IMPORT_PAGES:
                raise platform.PlatformError("Fayllar soni juda ko'p.")
            content = bytearray()
            while True:
                chunk = await part.read_chunk(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > config.MAX_UPLOAD_BYTES:
                    raise platform.PlatformError("Fayllar jami 20 MB dan oshmasin.", 413)
                content.extend(chunk)
            if content.startswith(b"%PDF-"):
                if assets:
                    raise platform.PlatformError("Bitta PDF yoki tartiblangan rasmlar yuboring.")
            else:
                if any(a["mime"] == "application/pdf" for a in assets):
                    raise platform.PlatformError("PDF va rasmlarni aralashtirmang.")
            source = await store_source(content, part.filename)
            paths.append(media_file(source["filename"]))
            assets.append(source)
        if not assets:
            raise platform.PlatformError("PDF yoki rasmlarni tanlang.")
        import_id = await platform.create_import(user(request)["id"], Path(assets[0]["original_name"]).stem, assets)
        committed = True
        return web.json_response({"id": import_id}, status=201)
    finally:
        if not committed:
            for path in paths:
                path.unlink(missing_ok=True)


async def import_detail(request):
    import_id, owner = request.match_info["import_id"], user(request)["id"]
    if request.method == "GET":
        return web.json_response(await platform.get_import(import_id, owner))
    data = await body(request)
    revision = await platform.save_import(import_id, owner, data["document"], data["revision"])
    return web.json_response({"revision": revision})


async def import_action(request):
    import_id, owner = request.match_info["import_id"], user(request)["id"]
    if request.match_info["action"] == "start":
        await start_collection(import_id, owner)
        return web.json_response({"ok": True})
    if request.match_info["action"] == "retry":
        await platform.retry_import(import_id, owner)
        return web.json_response({"ok": True})
    if request.match_info["action"] != "publish":
        raise web.HTTPNotFound()
    data = await body(request)
    test_id = await platform.publish_import(import_id, owner, data["revision"])
    async with get_db_connection() as db:
        test = await platform.one(db, "SELECT code FROM tests WHERE id = ?", (test_id,))
    return web.json_response({"test_id": test_id, "code": test["code"]})


async def student_test(request):
    return web.json_response(await platform.test_for_student(request.match_info["code"], user(request)["id"]))


async def student_action(request):
    test = await platform.load_test(request.match_info["code"])
    action = request.match_info["action"]
    if action == "result" and request.method == "GET":
        return web.json_response(await platform.submission_result(test["id"], user(request)["id"]))
    if request.method != "POST":
        raise web.HTTPMethodNotAllowed(request.method, ["POST"])
    data = await body(request)
    if action == "draft":
        revision = await platform.save_draft(test["id"], user(request)["id"], data["answers"], data["revision"])
        return web.json_response({"revision": revision})
    if action == "submit":
        await platform.submit_answers(test["id"], user(request), data["answers"])
        return web.json_response(await platform.submission_result(test["id"], user(request)["id"]))
    raise web.HTTPNotFound()


async def admin_tests(request):
    async with get_db_connection() as db:
        tests = await platform.rows(db, "SELECT id, code, title, status, total_questions FROM tests WHERE created_by = ? ORDER BY id DESC LIMIT 100", (user(request)["id"],))
    return web.json_response(tests)


async def results(request):
    return web.json_response(await platform.teacher_results(int(request.match_info["test_id"]), user(request)["id"]))


async def test_action(request):
    test_id, owner = int(request.match_info["test_id"]), user(request)["id"]
    action = request.match_info["action"]
    if action == "finish":
        from services.scoring_service import run_test_analytics_and_scoring
        await run_test_analytics_and_scoring(test_id, finish=True, owner_id=owner)
    elif action == "retry-grading":
        await platform.retry_grading(test_id, owner)
    else:
        raise web.HTTPNotFound()
    return web.json_response({"ok": True})


async def override(request):
    data = await body(request)
    if type(data.get("correct")) is not bool or not isinstance(data.get("feedback", ""), str):
        raise platform.PlatformError("Baho true/false bo'lishi kerak.")
    await platform.override_answer(int(request.match_info["test_id"]), user(request)["id"], int(request.match_info["answer_id"]), data["correct"], data.get("feedback", ""))
    return web.json_response({"ok": True})


async def report(request):
    test_id = int(request.match_info["test_id"])
    result = await platform.teacher_results(test_id, user(request)["id"])
    if result["test"]["status"] != "finished":
        raise platform.PlatformError("Hisobot test yakunlangach tayyor bo'ladi.", 409)
    from services.excel_service import generate_test_report_excel
    filename = await generate_test_report_excel(test_id)
    return web.FileResponse(filename, headers={"Content-Disposition": f'attachment; filename="test-{test_id}.xlsx"'})


async def asset(request):
    async with get_db_connection() as db:
        record = await platform.one(db, "SELECT a.*, i.owner_id FROM assets a JOIN imports i ON i.id = a.import_id WHERE a.id = ?", (request.match_info["asset_id"],))
        if not record:
            raise web.HTTPNotFound()
        if record["owner_id"] != user(request)["id"]:
            # Only approved crops referenced by the immutable published document are student-visible.
            test = await platform.one(db, "SELECT document_json FROM tests WHERE source_import_id = ? AND status IN ('active', 'finished')", (record["import_id"],))
            allowed = False
            if record["kind"] == "crop" and test:
                document = json.loads(test["document_json"])
                allowed = any(region.get("asset_id") == record["id"] for item in [*document["passages"], *document["questions"]] for region in item.get("media", []))
            if not allowed:
                raise web.HTTPNotFound()
    return web.FileResponse(media_file(record["filename"]), headers={"Content-Type": record["mime"]})


async def index(request):
    path = Path(config.FRONTEND_PATH).resolve()
    relative = request.match_info.get("path", "") or "index.html"
    filename = (path / relative).resolve()
    if not filename.is_relative_to(path) or not filename.is_file():
        if relative != "index.html":
            raise web.HTTPNotFound()
        return web.Response(text="Mini App hali build qilinmagan: cd web && npm ci && npm run build", status=503)
    return web.FileResponse(filename)


def create_web_app():
    app = web.Application(middlewares=[security], client_max_size=config.MAX_UPLOAD_BYTES + 1024 * 1024)
    app.add_routes([
        web.post("/api/session", session), web.get("/api/me", me),
        web.get("/api/admin/imports", imports), web.post("/api/admin/imports", imports),
        web.get("/api/admin/imports/{import_id}", import_detail), web.put("/api/admin/imports/{import_id}", import_detail),
        web.post("/api/admin/imports/{import_id}/{action}", import_action),
        web.get("/api/admin/tests", admin_tests), web.get("/api/admin/tests/{test_id}/results", results),
        web.get("/api/admin/tests/{test_id}/report", report),
        web.post("/api/admin/tests/{test_id}/answers/{answer_id}", override),
        web.post("/api/admin/tests/{test_id}/{action}", test_action),
        web.get("/api/tests/{code}", student_test),
        web.get("/api/tests/{code}/{action}", student_action), web.post("/api/tests/{code}/{action}", student_action),
        web.get("/api/assets/{asset_id}", asset),
        web.get("/{path:.*}", index),
    ])
    return app
