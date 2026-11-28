"""Explicitly curated exam-position practice; independent of exam attempts.

The bank dimension is retained for future teacher collections. Only the brand
bank is exposed now; ADMIN_IDS manages reviewed papers owned by ADMIN_IDS.
"""

import json
import time
import re

import config
from scripts.database.db import get_db_connection
from services.platform_service import PlatformError, one, rows, validate_answers
from services.test_document import TestDocument, normalize_answer, student_document

BANK = 'basirat'
ACTIVE = """ FROM practice_items i JOIN practice_sources s ON s.id=i.source_id
    WHERE s.bank_id=? AND s.enabled=1 """


def require_curator(user_id):
    if user_id not in config.ADMIN_IDS:
        raise PlatformError('Bu bo‘limni faqat Basirat administratori boshqaradi.', 403)


async def source_status(test_id, user_id):
    require_curator(user_id)
    async with get_db_connection() as db:
        test = await one(db, 'SELECT * FROM tests WHERE id=?', (test_id,))
        if not test or test['created_by'] not in config.ADMIN_IDS or not test['document_json'] or not test['template_id']:
            raise PlatformError('Basiratning savollari tayyor testi kerak.', 404)
        source = await one(db, 'SELECT id,enabled FROM practice_sources WHERE bank_id=? AND template_id=?', (BANK, test['template_id']))
    return {'enabled': bool(source and source['enabled']), 'source_id': source['id'] if source else None}


async def set_source(test_id, user_id, enabled):
    require_curator(user_id)
    if type(enabled) is not bool:
        raise PlatformError('Ko‘rinish qiymati noto‘g‘ri.')
    async with get_db_connection() as db:
        await db.execute('BEGIN IMMEDIATE')
        test = await one(db, 'SELECT * FROM tests WHERE id=?', (test_id,))
        if not test or test['created_by'] not in config.ADMIN_IDS or not test['document_json'] or not test['template_id']:
            raise PlatformError('Faqat Basiratning savollari tayyor testini qo‘shish mumkin.', 404)
        source = await one(db, 'SELECT * FROM practice_sources WHERE bank_id=? AND template_id=?', (BANK, test['template_id']))
        if source:
            await db.execute('UPDATE practice_sources SET enabled=? WHERE id=?', (int(enabled), source['id']))
        elif enabled:
            document = TestDocument.model_validate_json(test['document_json'])
            if document.publication_errors():
                raise PlatformError('Avval savollar va javob mezonlarini tekshiring.', 409)
            cursor = await db.execute('''INSERT INTO practice_sources(bank_id,template_id,source_test_id,title,
                publisher_name,document_json,created_by) VALUES (?,?,?,?,?,?,?)''',
                (BANK, test['template_id'], test_id, test['title'], test['publisher_name'], test['document_json'], user_id))
            passages = {p.id: p.model_dump_json() for p in document.passages}
            await db.executemany('INSERT INTO practice_items(source_id,number,question_json,passage_json) VALUES (?,?,?,?)',
                [(cursor.lastrowid, q.number, q.model_dump_json(), passages.get(q.passage_id)) for q in document.questions])
        await db.commit()
    return await source_status(test_id, user_id)


async def _item(db, item_id):
    record = await one(db, 'SELECT i.*,s.title,s.publisher_name' + ACTIVE + ' AND i.id=?', (BANK, item_id))
    if not record:
        raise PlatformError('Mashq savoli topilmadi.', 404)
    return record


async def grid(user_id):
    async with get_db_connection() as db:
        buckets = await rows(db, '''SELECT i.number,COUNT(*) AS total,
            SUM(c.id IS NOT NULL) AS checked,SUM(COALESCE(c.is_correct,0)) AS correct
            FROM practice_items i JOIN practice_sources s ON s.id=i.source_id
            LEFT JOIN practice_checks c ON c.id=(SELECT MAX(c2.id) FROM practice_checks c2
                WHERE c2.user_id=? AND c2.item_id=i.id AND c2.status='done')
            WHERE s.bank_id=? AND s.enabled=1 GROUP BY i.number ORDER BY i.number''', (user_id, BANK))
        position = await one(db, '''SELECT p.number FROM practice_positions p JOIN practice_items i ON i.id=p.item_id
            JOIN practice_sources s ON s.id=i.source_id WHERE p.user_id=? AND p.bank_id=? AND s.enabled=1
            ORDER BY p.updated_at DESC LIMIT 1''', (user_id, BANK))
    return {'bank': BANK, 'max_number': max((b['number'] for b in buckets), default=0),
            'numbers': buckets, 'resume_number': position['number'] if position else None}


async def open_number(number, user_id, item_id=None):
    if type(number) is not int or not 1 <= number <= 44 or item_id is not None and type(item_id) is not int:
        raise PlatformError('Savol raqami noto‘g‘ri.')
    async with get_db_connection() as db:
        await db.execute('BEGIN IMMEDIATE')
        if item_id is None:
            position = await one(db, 'SELECT item_id FROM practice_positions WHERE user_id=? AND bank_id=? AND number=?', (user_id, BANK, number))
            if position:
                found = await one(db, 'SELECT i.id' + ACTIVE + ' AND i.id=? AND i.number=?', (BANK, position['item_id'], number))
                item_id = found['id'] if found else None
        if item_id is None:
            first = await one(db, 'SELECT i.id' + ACTIVE + ' AND i.number=? ORDER BY i.id LIMIT 1', (BANK, number))
            item_id = first['id'] if first else None
        record = await _item(db, item_id)
        if record['number'] != number:
            raise PlatformError('Bu savol boshqa raqamga tegishli.', 404)
        await db.execute('''INSERT INTO practice_positions(user_id,bank_id,number,item_id,updated_at) VALUES (?,?,?,?,?)
            ON CONFLICT(user_id,bank_id,number) DO UPDATE SET item_id=excluded.item_id,updated_at=excluded.updated_at''',
            (user_id, BANK, number, item_id, time.time()))
        await db.commit()
    return await question(item_id, user_id)


async def question(item_id, user_id):
    async with get_db_connection() as db:
        record = await _item(db, item_id)
        progress = await one(db, 'SELECT * FROM practice_progress WHERE user_id=? AND item_id=?', (user_id, item_id))
        check = await one(db, '''SELECT c.*,j.status AS job_status FROM practice_checks c LEFT JOIN jobs j
            ON j.kind='practice_grade' AND j.target=CAST(c.id AS TEXT)
            WHERE c.user_id=? AND c.item_id=? AND c.id=?''', (user_id, item_id, progress['last_check_id'] if progress else None))
        navigation = await one(db, '''SELECT COUNT(*) AS total,SUM(i.id<=?) AS position,
            MAX(CASE WHEN i.id<? THEN i.id END) AS previous_id,MIN(CASE WHEN i.id>? THEN i.id END) AS next_id'''
            + ACTIVE + ' AND i.number=?', (item_id, item_id, item_id, BANK, record['number']))
    q = json.loads(record['question_json'])
    passage = json.loads(record['passage_json']) if record['passage_json'] else None
    document = student_document({'title': record['title'], 'questions': [q], 'passages': [passage] if passage else []})
    result = {'id': item_id, 'number': record['number'], 'source_title': record['title'],
              'publisher_name': record['publisher_name'], 'question': document['questions'][0],
              'passage': document['passages'][0] if passage else None,
              'answer': json.loads(progress['answer_json']) if progress else ({p['id']: '' for p in q['parts']} if q['parts'] else ''),
              'revision': progress['revision'] if progress else 0, **navigation, 'check': None}
    if check:
        result['check'] = {'id': check['id'], 'answer': json.loads(check['answer_json']),
                           'status': 'failed' if check['job_status'] == 'failed' and check['status'] == 'pending' else check['status'],
                           'correct': bool(check['is_correct']) if check['status'] == 'done' else None, 'feedback': check['feedback']}
        result['solution'] = {'answer': q['answer'], 'accepted_answers': q['accepted_answers'],
                              'rubric': q['rubric'] if q['kind'] == 'open' else '',
                              'audio_url': f"/api/practice/items/{item_id}/assets/{q['explanation_audio']}" if q.get('explanation_audio') else None}
    return result


def _clean(record, answer):
    q = json.loads(record['question_json'])
    fake = {'question_num': q['number'], 'question_type': 'open' if q['kind'] == 'open' else 'closed', 'content_json': record['question_json']}
    return q, validate_answers([fake], {str(q['number']): answer})[str(q['number'])]


async def _save(db, record, user_id, answer, revision):
    if type(revision) is not int or revision < 0:
        raise PlatformError('Saqlash versiyasi noto‘g‘ri.')
    q, cleaned = _clean(record, answer)
    pending = await one(db, "SELECT id FROM practice_checks WHERE user_id=? AND item_id=? AND status='pending' LIMIT 1", (user_id, record['id']))
    if pending:
        raise PlatformError('Avval yuborilgan javob tekshirilishini kuting.', 409)
    progress = await one(db, 'SELECT revision FROM practice_progress WHERE user_id=? AND item_id=?', (user_id, record['id']))
    if (progress['revision'] if progress else 0) != revision:
        raise PlatformError('Javob boshqa oynada o‘zgargan. Savolni qayta oching.', 409)
    encoded = json.dumps(cleaned, ensure_ascii=False, sort_keys=True)
    await db.execute('''INSERT INTO practice_progress(user_id,item_id,answer_json,revision) VALUES (?,?,?,?)
        ON CONFLICT(user_id,item_id) DO UPDATE SET answer_json=excluded.answer_json,revision=excluded.revision,last_check_id=NULL''',
        (user_id, record['id'], encoded, revision + 1))
    return q, cleaned, encoded


async def save_answer(item_id, user_id, answer, revision):
    async with get_db_connection() as db:
        await db.execute('BEGIN IMMEDIATE')
        record = await _item(db, item_id)
        await _save(db, record, user_id, answer, revision)
        await db.commit()
    return {'revision': revision + 1}


async def check_answer(item_id, user_id, answer, revision, request_key):
    if not isinstance(request_key, str) or not re.fullmatch(r'[a-f0-9]{32}', request_key):
        raise PlatformError('So‘rov kaliti noto‘g‘ri.')
    async with get_db_connection() as db:
        await db.execute('BEGIN IMMEDIATE')
        record = await _item(db, item_id)
        q, cleaned = _clean(record, answer)
        encoded = json.dumps(cleaned, ensure_ascii=False, sort_keys=True)
        prior = await one(db, 'SELECT * FROM practice_checks WHERE user_id=? AND request_key=?', (user_id, request_key))
        if prior:
            if prior['item_id'] != item_id or prior['answer_json'] != encoded:
                raise PlatformError('Bu so‘rov boshqa javob uchun ishlatilgan.', 409)
        else:
            if not cleaned or isinstance(cleaned, dict) and not all(cleaned.values()):
                raise PlatformError('Tekshirish uchun barcha qismlarga javob yozing.')
            count = await one(db, 'SELECT COUNT(*) AS n FROM practice_checks WHERE user_id=? AND created_at>?', (user_id, time.time() - 60))
            if count['n'] >= 30:
                raise PlatformError('Juda ko‘p so‘rov. Birozdan keyin davom eting.', 429)
            await _save(db, record, user_id, answer, revision)
            correct, status = None, 'done'
            if q['kind'] != 'open':
                correct = int(cleaned == q['answer'])
            elif not q['parts'] and q['accepted_answers'] and normalize_answer(cleaned) in {normalize_answer(a) for a in q['accepted_answers']}:
                correct = 1
            elif q['rubric']:
                status = 'pending'
            else:
                correct = 0
            cursor = await db.execute('''INSERT INTO practice_checks(user_id,item_id,request_key,answer_json,status,is_correct,created_at)
                VALUES (?,?,?,?,?,?,?)''', (user_id, item_id, request_key, encoded, status, correct, time.time()))
            await db.execute('UPDATE practice_progress SET last_check_id=? WHERE user_id=? AND item_id=?', (cursor.lastrowid, user_id, item_id))
            if status == 'pending':
                await db.execute("INSERT INTO jobs(kind,target) VALUES ('practice_grade',?)", (str(cursor.lastrowid),))
            await db.commit()
    return await question(item_id, user_id)


async def grade_check(check_id):
    from services.ai_service import ai_evaluator
    async with get_db_connection() as db:
        record = await one(db, '''SELECT c.*,i.question_json,i.passage_json FROM practice_checks c
            JOIN practice_items i ON i.id=c.item_id WHERE c.id=?''', (check_id,))
    if not record or record['status'] != 'pending':
        return
    q = json.loads(record['question_json'])
    passage = json.loads(record['passage_json']) if record['passage_json'] else None
    rubric = f"Savol: {q['text']}\nQismlar: {json.dumps(q['parts'], ensure_ascii=False)}\nO‘qituvchi mezoni: {q['rubric']}"
    if passage:
        rubric += '\nUmumiy matn: ' + passage['text']
    answer = json.loads(record['answer_json'])
    correct, feedback = await ai_evaluator.evaluate_open_answer(q['number'], rubric,
        json.dumps(answer, ensure_ascii=False) if isinstance(answer, dict) else answer)
    async with get_db_connection() as db:
        await db.execute("UPDATE practice_checks SET status='done',is_correct=?,feedback=? WHERE id=? AND status='pending'", (int(correct), feedback, check_id))
        await db.commit()


async def retry_check(item_id, user_id):
    async with get_db_connection() as db:
        await db.execute('BEGIN IMMEDIATE')
        await _item(db, item_id)
        record = await one(db, "SELECT id FROM practice_checks WHERE user_id=? AND item_id=? AND status='pending' ORDER BY id DESC LIMIT 1", (user_id, item_id))
        if not record:
            raise PlatformError('Tekshirish kutilayotgan javob yo‘q.', 409)
        await db.execute("UPDATE jobs SET status='queued',attempts=0,available_at=0,error=NULL WHERE kind='practice_grade' AND target=? AND status='failed'", (str(record['id']),))
        await db.commit()
    return await question(item_id, user_id)


async def asset(item_id, asset_id, user_id):
    async with get_db_connection() as db:
        record = await _item(db, item_id)
        q = json.loads(record['question_json'])
        passage = json.loads(record['passage_json']) if record['passage_json'] else {}
        media = {region['asset_id'] for item in (q, passage) for region in item.get('media', [])}
        audio = q.get('explanation_audio') == asset_id and bool(asset_id)
        if audio and not await one(db, 'SELECT id FROM practice_checks WHERE user_id=? AND item_id=? LIMIT 1', (user_id, item_id)):
            raise PlatformError('Avval shu savolga javob yuboring.', 403)
        found = await one(db, 'SELECT * FROM assets WHERE id=?', (asset_id,))
        if not found or (found['kind'] != 'explanation' or not audio) and (found['kind'] != 'crop' or asset_id not in media):
            raise PlatformError('Fayl topilmadi.', 404)
        return found
