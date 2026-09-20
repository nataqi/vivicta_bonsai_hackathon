import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import app.adviser_learning as learning
import app.post_meeting as post_meeting
from app.coaching import CoachingArea, CompletedMeetingData


@contextmanager
def db_connection(path):
    connection = sqlite3.connect(path)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


class AdviserLearningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        post_meeting.store.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "nested" / "learning.db"
        self.repository = learning.SQLiteRepository(self.db_path)

    def tearDown(self):
        post_meeting.store.clear()
        self.temp_dir.cleanup()

    def candidate(self, *, record_id=None, takeaway=None):
        return learning.LearningCandidate(
            record_id=record_id or uuid4(),
            adviser_id=learning.DEMO_ADVISER_ID,
            focus_areas=[CoachingArea.OPEN_QUESTIONS],
            strength_areas=[CoachingArea.OPEN_QUESTIONS],
            improvement_areas=[CoachingArea.STAY_BEFORE_SOLVING],
            takeaway_area=takeaway,
        )

    def registered_session(self):
        session_id = str(uuid4())
        session = post_meeting.store.register(
            session_id,
            CompletedMeetingData(
                turns=({"text": "CUSTOMER TRANSCRIPT SECRET"},),
                selected_focus=(CoachingArea.OPEN_QUESTIONS,),
                events=(),
                nudges=(),
            ),
        )
        session.report = post_meeting.PostMeetingReport(
            strengths=["CUSTOMER REPORT SECRET"],
            improvements=["Try an open question."],
            focus_summary="Open questions",
            takeaway="Ask what would help.",
        )
        session.strength_areas = (CoachingArea.OPEN_QUESTIONS,)
        session.improvement_areas = (CoachingArea.STAY_BEFORE_SOLVING,)
        return session

    def test_database_and_tables_are_created_automatically(self):
        self.assertTrue(self.db_path.exists())
        with db_connection(self.db_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("select name from sqlite_master where type = 'table'")
            }
        self.assertTrue({"adviser_profiles", "adviser_learning_history"}.issubset(tables))

    def test_focus_and_learning_survive_new_repository_instance(self):
        record_id = uuid4()
        self.repository.save_focus(learning.DEMO_ADVISER_ID, [CoachingArea.OPEN_QUESTIONS])
        self.repository.save(self.candidate(record_id=record_id))
        reopened = learning.SQLiteRepository(self.db_path)
        self.assertEqual(reopened.read_profile(learning.DEMO_ADVISER_ID), [CoachingArea.OPEN_QUESTIONS])
        history = reopened.read_history(learning.DEMO_ADVISER_ID)
        self.assertEqual(history.records[0].id, record_id)

    def test_focus_validation_rejects_empty_and_duplicate_values(self):
        with self.assertRaises(ValueError):
            learning.FocusRequest(focusAreas=[])
        with self.assertRaises(ValueError):
            learning.FocusRequest(focusAreas=["open_questions", "open_questions"])

    def test_first_use_and_recent_history_insight(self):
        self.assertIsNone(learning.insight_for_history(()))
        adviser_id = learning.DEMO_ADVISER_ID
        older = learning.LearningRecord(
            id=uuid4(), adviser_id=adviser_id,
            focus_areas=[CoachingArea.STAY_BEFORE_SOLVING],
            strength_areas=[], improvement_areas=[CoachingArea.STAY_BEFORE_SOLVING],
            created_at=datetime.now(timezone.utc),
        )
        latest = learning.LearningRecord(
            id=uuid4(), adviser_id=adviser_id,
            focus_areas=[CoachingArea.OPEN_QUESTIONS],
            strength_areas=[CoachingArea.STAY_BEFORE_SOLVING], improvement_areas=[],
            created_at=datetime.now(timezone.utc),
        )
        self.assertIn("more consistency", learning.insight_for_history((latest, older)))

    def test_area_label_is_capitalized_when_it_begins_an_insight(self):
        adviser_id = learning.DEMO_ADVISER_ID
        older = learning.LearningRecord(
            id=uuid4(), adviser_id=adviser_id,
            focus_areas=[CoachingArea.PACE_AND_PAUSES],
            strength_areas=[], improvement_areas=[CoachingArea.PACE_AND_PAUSES],
            created_at=datetime.now(timezone.utc),
        )
        latest = learning.LearningRecord(
            id=uuid4(), adviser_id=adviser_id,
            focus_areas=[CoachingArea.PACE_AND_PAUSES],
            strength_areas=[], improvement_areas=[CoachingArea.PACE_AND_PAUSES],
            created_at=datetime.now(timezone.utc),
        )

        self.assertTrue(
            learning.insight_for_history((latest, older)).startswith("A calm pace")
        )

    async def test_home_focus_and_insight_come_from_sqlite(self):
        self.repository.save(self.candidate())
        with patch.object(learning, "repository", return_value=self.repository):
            response = await learning.adviser_home()
        self.assertEqual(response.history_state, "ready")
        self.assertEqual(response.focus_areas, [CoachingArea.OPEN_QUESTIONS])
        self.assertIn("practising", response.recent_insight)

    async def test_completion_persists_allowlist_and_skipped_reflection_cleanup(self):
        session = self.registered_session()
        with patch.object(learning, "repository", return_value=self.repository):
            response = await learning.complete_post_meeting(session.snapshot.session_id)
        self.assertTrue(response.learning_saved)
        self.assertTrue(response.cleanup_complete)
        self.assertIsNone(post_meeting.store.get(session.snapshot.session_id))
        row = self.repository.read_history(learning.DEMO_ADVISER_ID).records[0]
        self.assertIsNone(row.takeaway_area)
        with db_connection(self.db_path) as connection:
            raw = connection.execute("select * from adviser_learning_history").fetchone()
        self.assertNotIn("CUSTOMER", repr(raw))
        self.assertNotIn("REPORT", repr(raw))

    async def test_completed_reflection_takeaway_is_canonical(self):
        session = self.registered_session()
        session.takeaway_area = CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES
        with patch.object(learning, "repository", return_value=self.repository):
            await learning.complete_post_meeting(session.snapshot.session_id)
        row = self.repository.read_history(learning.DEMO_ADVISER_ID).records[0]
        self.assertEqual(row.takeaway_area, CoachingArea.ACKNOWLEDGING_EMOTIONAL_CUES)

    async def test_database_failure_still_deletes_temporary_session(self):
        session = self.registered_session()
        with patch.object(learning, "repository", side_effect=learning.SQLiteUnavailable()):
            response = await learning.complete_post_meeting(session.snapshot.session_id)
        self.assertFalse(response.learning_saved)
        self.assertTrue(response.cleanup_complete)
        self.assertIsNone(post_meeting.store.get(session.snapshot.session_id))

    async def test_duplicate_completion_creates_one_history_row(self):
        session = self.registered_session()
        with patch.object(learning, "repository", return_value=self.repository):
            first = await learning.complete_post_meeting(session.snapshot.session_id)
            second = await learning.complete_post_meeting(session.snapshot.session_id)
        self.assertTrue(first.learning_saved)
        self.assertFalse(second.learning_saved)
        with db_connection(self.db_path) as connection:
            count = connection.execute("select count(*) from adviser_learning_history").fetchone()[0]
        self.assertEqual(count, 1)

    def test_malformed_stored_data_fails_safely(self):
        with db_connection(self.db_path) as connection:
            connection.execute(
                "insert into adviser_learning_history values (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid4()), learning.DEMO_ADVISER_ID, "not-json", "[]", "[]", None, datetime.now(timezone.utc).isoformat()),
            )
        result = self.repository.read_history(learning.DEMO_ADVISER_ID)
        self.assertTrue(result.malformed)
        self.assertEqual(result.records, ())

    def test_history_limit_counts_valid_rows_after_malformed_rows(self):
        base_time = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        valid_ids = [uuid4() for _ in range(5)]
        with db_connection(self.db_path) as connection:
            connection.execute(
                "insert into adviser_learning_history values (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    learning.DEMO_ADVISER_ID,
                    "not-json",
                    "[]",
                    "[]",
                    None,
                    (base_time.replace(minute=59)).isoformat(),
                ),
            )
            for index, record_id in enumerate(valid_ids):
                created_at = base_time.replace(minute=54 - index)
                connection.execute(
                    "insert into adviser_learning_history values (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(record_id),
                        learning.DEMO_ADVISER_ID,
                        '["open_questions"]',
                        '[]',
                        '["stay_before_solving"]',
                        None,
                        created_at.isoformat(),
                    ),
                )

        result = self.repository.read_history(learning.DEMO_ADVISER_ID)

        self.assertTrue(result.malformed)
        self.assertEqual([record.id for record in result.records], valid_ids)


if __name__ == "__main__":
    unittest.main()
