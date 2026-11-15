"""Offline wiring of transcript Decisions, task completion and calendar actions."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from inloop_app import InLoop


class AutomationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.app=InLoop(Path(self.directory.name)/'workspace.sqlite3')
        self.app.http=object()

    def tearDown(self):
        self.app.store.db.close()
        self.directory.cleanup()

    def event(self,identity,text,at=1893844800):
        self.app.store.add_event(dict(type='transcript',event_id=identity,text=text,audio_start_at=at,
            speaker_turns=[dict(speaker_id=0,speaker_key='speaker-0',text=text)]))
        return self.app.store.event(identity)

    async def test_calendar_actions_reconstructs_verified_joined_source_and_exposes_status(self):
        self.event('one','Schedule design review',at=1893844800)
        self.event('two','tomorrow at 5pm.',at=1893844802)
        task=self.app.store.add_task('Schedule design review tomorrow at 5pm.',kind='calendar',
            source_id='one',quote='Schedule design review',source_spans=[
                dict(source_id='one',quote='Schedule design review'),dict(source_id='two',quote='tomorrow at 5pm.')])
        async def processed(http,calendar,item,source):
            self.assertEqual(source['text'],task['title'])
            self.assertEqual(source['said_at'],1893844800)
            return self.app.calendar_automation.save(item,source,'created',message='Calendar event created.')
        with mock.patch.object(self.app.calendar_automation,'process',side_effect=processed) as process, mock.patch.object(self.app,'broadcast',new=mock.AsyncMock()):
            await self.app.calendar_actions([task])
            process.assert_awaited_once()
        visible=self.app.snapshot()['tasks'][0]
        self.assertEqual(visible['calendar_action']['status'],'created')
        self.assertEqual(visible['calendar_action']['message'],'Calendar event created.')

    async def test_calendar_actions_rejects_tampered_persisted_source_quote(self):
        self.event('one','Schedule design review')
        self.event('two','tomorrow at 5pm.',at=1893844802)
        task=self.app.store.add_task('Schedule design review tomorrow at 5pm.',kind='calendar',
            source_id='one',quote='Schedule design review',source_spans=[
                dict(source_id='one',quote='Schedule design review'),dict(source_id='two',quote='tomorrow at 5pm.')])
        self.app.store.db.execute('UPDATE task_sources SET quote=? WHERE task_id=? AND ordinal=1',('invented date',task['id']))
        self.app.store.db.commit()
        with mock.patch.object(self.app.calendar_automation,'process',new=mock.AsyncMock()) as process, mock.patch.object(self.app,'broadcast',new=mock.AsyncMock()):
            await self.app.calendar_actions([task])
            process.assert_not_awaited()

    async def test_explicit_completion_updates_existing_task_once_without_calendar_calls(self):
        original=self.app.store.add_task('Send the revised paper to Maya.')
        self.event('completed','I finished sending the revised paper to Maya.')
        def post(url,**kwargs):
            questions=kwargs['json']['questions'];answers={}
            for name,question in questions.items():
                choices=list(question['criteria']);choice='task_0' if name.startswith('completion_') else 'none'
                scores={key:(.99 if key==choice else .01/(len(choices)-1)) for key in choices}
                answers[name]=dict(type='choice',choice=choice,confidence=.99,probabilities=scores)
            response=mock.Mock(status=200);response.json=mock.AsyncMock(return_value={'answers':answers})
            context=mock.MagicMock();context.__aenter__=mock.AsyncMock(return_value=response);context.__aexit__=mock.AsyncMock(return_value=None)
            return context
        self.app.http=mock.Mock(post=mock.Mock(side_effect=post))
        with mock.patch('scripts.benchmark_gemini_motion.key_from_file',return_value='offline-test-value'), mock.patch.object(self.app.calendar_automation,'process',new=mock.AsyncMock()) as process:
            self.assertEqual(await self.app.extract(['completed']),[])
            self.assertEqual(self.app.store.tasks()[0]['status'],'done')
            self.assertEqual(await self.app.extract(['completed']),[])
            process.assert_not_awaited()
        rows=self.app.store.db.execute('SELECT task_id,source_id,operation FROM task_actions').fetchall()
        self.assertEqual([tuple(row) for row in rows],[(original['id'],'completed','complete')])
