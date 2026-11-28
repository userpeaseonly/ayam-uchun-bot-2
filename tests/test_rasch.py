import asyncio
import json
import math

import pytest
from openpyxl import load_workbook

import config
from scripts.database.db import get_db_connection, init_db
from scripts.database.models import add_answer, add_question, create_submission, create_test
from services import platform_service as platform
from services.rasch import calibrate
from services.scoring_service import run_test_analytics_and_scoring


def test_matches_published_ltm_lsat_fixed_discrimination_reference():
    # Rizopoulos (2006), JSS 17(5), section 3.1, rasch(LSAT,
    # constraint=cbind(6,1)); https://www.jstatsoft.org/article/view/v017i05
    # LSAT response frequencies in lexicographic 00000..11111 order.
    frequencies = [3, 6, 2, 11, 1, 1, 3, 4, 1, 8, 0, 16, 0, 3, 2, 15,
                   10, 29, 14, 81, 3, 28, 15, 80, 16, 56, 21, 173, 11, 61, 28, 298]
    matrix = [[int(c) for c in f'{i:05b}'] for i, count in enumerate(frequencies) for _ in range(count)]
    result = calibrate(matrix)
    assert result['converged']
    assert [item['difficulty'] for item in result['items']] == pytest.approx(
        [-2.8719712, -1.0630294, -0.2576109, -1.3880588, -2.2187785], abs=2e-5)
    # T is a standardized ability, not a percentage or a capped sum of points.
    scores = [person['score'] for person in result['persons']]
    assert sum(scores) / len(scores) == pytest.approx(50)
    assert math.sqrt(sum((s - 50) ** 2 for s in scores) / len(scores)) == pytest.approx(10)


@pytest.mark.parametrize('matrix,item_count', [([], 5), ([[1, 0, 1]], 3),
    ([[0, 0], [0, 0]], 2), ([[1, 1], [1, 1]], 2), ([[1, 0], [0, 1]], 2)])
def test_unidentifiable_cohorts_never_get_fabricated_scores(matrix, item_count):
    result = calibrate(matrix, item_count=item_count)
    assert result['status'] == 'unavailable'
    assert len(result['items']) == item_count
    assert all(p['score'] is None and p['theta'] is None for p in result['persons'])
    json.dumps(result, allow_nan=False)


def test_extremes_ties_permutation_and_nonconvergence():
    matrix = [[1, 0, 0, 0], [1, 0, 1, 0], [1, 0, 0, 1], [1, 0, 1, 1]]
    result = calibrate(matrix)
    assert result['status'] == 'provisional'
    assert 'small_cohort' in result['warnings'] and 'extreme_items' in result['warnings']
    assert result['items'][0]['difficulty'] is None and result['items'][1]['difficulty'] is None
    people = result['persons']
    assert people[0]['score'] < people[1]['score'] == people[2]['score'] < people[3]['score']
    assert all(math.isfinite(p['theta']) and 0 < p['se'] < 2 for p in people)
    reversed_result = calibrate([list(reversed(row)) for row in reversed(matrix)])
    assert [p['score'] for p in reversed_result['persons']] == pytest.approx([p['score'] for p in reversed(people)])
    failure = calibrate(matrix, max_iterations=0)
    assert failure['status'] == 'unavailable' and 'nonconvergence' in failure['warnings']
    assert all(p['score'] is None for p in failure['persons'])


@pytest.mark.parametrize('matrix', [[[1], [1, 0]], [[None]], [[0.5]], [[2]], [[True]]])
def test_pending_missing_or_partial_credit_is_not_silently_imputed(matrix):
    with pytest.raises(ValueError):
        calibrate(matrix)


@pytest.mark.asyncio
async def test_atomic_rasch_reveal_audit_export_and_immutable_finalization(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_PATH', str(tmp_path / 'rasch.sqlite3'))
    monkeypatch.chdir(tmp_path)
    await init_db()
    test_id = await create_test('R-100', 'Rash sinovi', 111, 4, 1)
    qs = [await add_question(test_id, j + 1, 'open' if j == 3 else 'closed', correct_answer='A', assigned_points=99) for j in range(4)]
    matrix = [[0, 0, 0, 0], [1, 0, 0, 0], [0, 1, 0, 0], [1, 1, 0, 0], [1, 1, 1, 1]]
    for i, row in enumerate(matrix):
        sid = await create_submission(test_id, 1000 + i, f'Student {i}', None, None)
        for qid, value in zip(qs, row):
            await add_answer(sid, qid, 'answer', is_correct=value)
    before = await platform.submission_result(test_id, 1000)
    assert 'score' not in before and 'scoring' not in before
    await asyncio.gather(*(run_test_analytics_and_scoring(test_id, finish=True, owner_id=111) for _ in range(2)))
    results = await platform.teacher_results(test_id, 111)
    assert results['scoring']['status'] == 'provisional'
    assert 'scoring_json' not in results['test']
    people = {s['user_id']: s for s in results['submissions']}
    assert people[1001]['total_score'] == people[1002]['total_score']
    assert people[1001]['rank'] == people[1002]['rank'] == 3
    assert people[1004]['rank'] == 1 and people[1004]['total_correct'] == 4
    assert all(q['assigned_points'] is None and q['assigned_tier'] == 'rasch' for q in results['questions'])
    student = await platform.submission_result(test_id, 1001)
    assert student['scoring']['label'] == 'Rash modeli asosidagi mashq natijasi'
    assert all(key not in json.dumps(student) for key in ('difficulty', 'persons', 'items', 'rasch_theta'))
    with pytest.raises(platform.PlatformError):
        await platform.teacher_results(test_id, 1001)
    async with get_db_connection() as db:
        saved = await platform.one(db, 'SELECT scoring_json FROM tests WHERE id=?', (test_id,))
        snapshot = json.loads(saved['scoring_json'])
        assert snapshot['version'] and snapshot['persons'][0]['submission_id']
        assert (await platform.one(db, "SELECT COUNT(*) AS n FROM jobs WHERE kind='notify'"))['n'] == len(matrix)
    def forbidden(*args, **kwargs):
        raise AssertionError('Finalized results must not be recalibrated')
    monkeypatch.setattr('services.rasch.calibrate', forbidden)
    await run_test_analytics_and_scoring(test_id, finish=True, owner_id=111)
    assert await platform.submission_result(test_id, 1001) == student
    from services.excel_service import generate_test_report_excel
    book = load_workbook(await generate_test_report_excel(test_id))
    assert book['Natijalar Reytingi'].cell(1, 6).value == 'Mashq natijasi (T-ball)'
    assert book['Savollar Tahlili'].cell(1, 6).value == 'Qiyinlik (logit)'
    assert 'Rash metodikasi' in book.sheetnames
    assert any('rasch-mml-eap-1' in str(row[1].value) for row in book['Rash metodikasi'])


@pytest.mark.asyncio
async def test_upgrade_preserves_old_active_and_finished_scoring(tmp_path, monkeypatch):
    from scripts.database import migrations
    monkeypatch.setattr(config, 'DB_PATH', str(tmp_path / 'old.sqlite3'))
    all_migrations = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations[:6])
    await init_db()
    async with get_db_connection() as db:
        await db.executemany("INSERT INTO tests(id,code,title,created_by,total_questions,status) VALUES (?,?,?,111,1,?)",
                             [(1, 'OLD-1', 'Old finished', 'finished'), (2, 'OLD-2', 'Old active', 'active')])
        await db.execute("INSERT INTO submissions(test_id,user_id,total_score,rank) VALUES (1,1001,42.7,1)")
        await db.execute("INSERT INTO questions(test_id,question_num,question_type,assigned_tier,assigned_points) VALUES (1,1,'closed','hard',2.5)")
        await db.commit()
    monkeypatch.setattr(migrations, 'MIGRATIONS', all_migrations)
    await init_db()
    await init_db()
    await run_test_analytics_and_scoring(1, finish=True, owner_id=111)
    async with get_db_connection() as db:
        assert (await platform.one(db, 'SELECT total_score FROM submissions WHERE test_id=1'))['total_score'] == 42.7
        assert (await platform.one(db, 'SELECT assigned_points FROM questions WHERE test_id=1'))['assigned_points'] == 2.5
        assert all(t['scoring_method'] == 'legacy_tertile' for t in await platform.rows(db, 'SELECT * FROM tests'))
    new_id = await create_test('NEW-1', 'New', 111, 1, 0)
    async with get_db_connection() as db:
        assert (await platform.one(db, 'SELECT scoring_method FROM tests WHERE id=?', (new_id,)))['scoring_method'] == 'rasch_v1'
