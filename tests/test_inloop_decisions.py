"""Decision-only action classification: closed choices, extractive text, safe migration."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from inloop_app import (DECISION_ENDPOINT, DECISION_MODEL, TASK_CRITERIA, InLoop,
                        Workspace, task_answer, task_candidates)


def answer(choice,confidence=.9):
    other=(1-confidence)/3
    return dict(type='choice',choice=choice,confidence=confidence,
                probabilities={key:confidence if key==choice else other for key in TASK_CRITERIA})


class FakeResponse:
    def __init__(self,data,status=200):self.data=data;self.status=status
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def json(self):return self.data


class FakeHTTP:
    def __init__(self,data,status=200):self.data=data;self.status=status;self.calls=[]
    def post(self,url,**kwargs):
        self.calls.append((url,kwargs))
        return FakeResponse(self.data,self.status)


class DecisionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=InLoop(Path(self.temp.name)/'workspace.db')
        self.key=mock.patch('scripts.benchmark_gemini_motion.key_from_file',return_value='test-key')
        self.key.start()

    async def asyncTearDown(self):
        self.key.stop();self.app.store.db.close();self.temp.cleanup()

    def events(self,texts):
        for index,text in enumerate(texts):
            self.app.store.add_event(dict(type='transcript',event_id=str(index),text=text))
        return [str(index) for index in range(len(texts))]

    async def test_classifies_each_candidate_without_generated_text_or_calendar_write(self):
        ids=self.events(['Please test Bluetooth.','Schedule the demo tomorrow at ten.','The sky is blue.','Team action item: coordinate the integration handoff.'])
        self.app.http=FakeHTTP({'answers':{f'candidate_{i}':answer(kind) for i,kind in enumerate(['todo','calendar','none','action_item'])}})
        tasks=await self.app.extract(ids)
        self.assertEqual([task['kind'] for task in tasks],['todo','calendar','action_item'])
        for task in tasks:
            self.assertEqual(task['title'],self.app.store.event(task['source_id'])['text'])
            self.assertEqual(task['quote'],task['title'])
            self.assertEqual(task['decision_model'],DECISION_MODEL)
            self.assertIsNone(task['owner'])
            self.assertEqual(task['priority'],'normal')
        self.assertEqual(len(self.app.http.calls),1)
        url,options=self.app.http.calls[0]
        self.assertEqual(url,DECISION_ENDPOINT)
        self.assertEqual(options['json']['model'],DECISION_MODEL)
        self.assertEqual(len(options['json']['questions']),4)
        for question in options['json']['questions'].values():
            self.assertEqual(question['type'],'choice')
            self.assertEqual(set(question['criteria']),set(TASK_CRITERIA))
        self.assertNotIn('generateContent',url)

    async def test_malformed_last_answer_fails_entire_batch_before_any_save(self):
        ids=self.events(['Please test Bluetooth.','Please write the demo.'])
        invalid=answer('todo');invalid['probabilities']['todo']=float('nan')
        self.app.http=FakeHTTP({'answers':{'candidate_0':answer('todo'),'candidate_1':invalid}})
        with self.assertRaises(ValueError):await self.app.extract(ids)
        self.assertEqual(self.app.store.tasks(),[])

    async def test_low_confidence_and_none_create_nothing(self):
        ids=self.events(['Maybe do this.','The sky is blue.'])
        self.app.http=FakeHTTP({'answers':{'candidate_0':dict(type='choice',choice='todo',confidence=.5,probabilities=dict(todo=.5,none=.5,calendar=0,action_item=0)),'candidate_1':answer('none')}})
        self.assertEqual(await self.app.extract(ids),[])

    async def test_missing_answer_or_provider_failure_never_falls_back(self):
        ids=self.events(['Please test Bluetooth.'])
        self.app.http=FakeHTTP({'answers':{}})
        with self.assertRaises(ValueError):await self.app.extract(ids)
        self.app.http=FakeHTTP({'private_error':'do not expose'},status=429)
        with self.assertRaises(RuntimeError) as caught:await self.app.extract(ids)
        self.assertNotIn('private_error',str(caught.exception))
        self.assertEqual(len(self.app.http.calls),1)
        self.assertEqual(self.app.store.tasks(),[])

    async def test_bare_placeholder_commands_never_reach_provider(self):
        ids=self.events(['Do this.','Just do this.','Add item.','Please add a task.','Mention it.','Fix that.'])
        self.app.http=FakeHTTP({})
        self.assertEqual(await self.app.extract(ids),[])
        self.assertEqual(self.app.http.calls,[])

    async def test_uncertain_action_is_not_saved(self):
        ids=self.events(['Please send the revised paper to Maya.'])
        self.app.http=FakeHTTP({'answers':{'candidate_0':dict(type='choice',choice='todo',confidence=.79,probabilities=dict(todo=.79,none=.21,calendar=0,action_item=0))}})
        self.assertEqual(await self.app.extract(ids),[])

    async def test_split_deadline_uses_previous_caption_and_keeps_both_sources(self):
        for index,text in enumerate(['I need to submit','a paper this Wednesday at 5PM.']):
            self.app.store.add_event(dict(type='transcript',event_id=str(index),text=text,timestamp=1000+index*4,
                                         speaker_turns=[dict(speaker_key='stream:0')]))
        decision=dict(type='choice',choice='calendar',confidence=.59,
                      probabilities=dict(calendar=.59,todo=.36,action_item=.01,none=.04))
        self.app.http=FakeHTTP({'answers':{'candidate_0':decision}})
        tasks=await self.app.extract(['1'])
        self.assertEqual([t['title'] for t in tasks],['I need to submit a paper this Wednesday at 5PM.'])
        spans=self.app.store.db.execute('SELECT source_id,quote FROM task_sources ORDER BY ordinal').fetchall()
        self.assertEqual([r['source_id'] for r in spans],['0','1'])
        self.assertEqual(tasks[0]['quote'],'I need to submit')

    async def test_explicit_completion_matches_existing_task_with_audit(self):
        task=self.app.store.add_task('Test the Bluetooth connection.')
        ids=self.events(['I finished testing the Bluetooth connection.'])
        complete=dict(type='choice',choice='task_0',confidence=.96,probabilities=dict(none=.04,task_0=.96))
        self.app.http=FakeHTTP({'answers':{'candidate_0':answer('none'),'completion_0':complete}})
        self.assertEqual(await self.app.extract(ids),[])
        self.assertEqual(self.app.store.tasks()[0]['status'],'done')
        row=self.app.store.db.execute('SELECT * FROM task_actions').fetchone()
        self.assertEqual((row['task_id'],row['source_id'],row['operation']),(task['id'],'0','complete'))

    async def test_negated_or_uncertain_completion_does_not_change_task(self):
        self.app.store.add_task('Test the Bluetooth connection.')
        ids=self.events(['I have not finished testing Bluetooth.'])
        for confidence in (.2,.89):
            choice='task_0' if confidence>.5 else 'none'
            decision=dict(type='choice',choice=choice,confidence=max(confidence,1-confidence),probabilities=dict(task_0=confidence,none=1-confidence))
            self.app.http=FakeHTTP({'answers':{'candidate_0':answer('none'),'completion_0':decision}})
            await self.app.extract(ids)
            self.assertEqual(self.app.store.tasks()[0]['status'],'open')
            self.assertEqual(self.app.store.db.execute('SELECT count(*) FROM task_actions').fetchone()[0],0)

    async def test_invalid_completion_prevents_all_batch_changes(self):
        self.app.store.add_task('Test the Bluetooth connection.')
        ids=self.events(['I finished testing Bluetooth.'])
        self.app.http=FakeHTTP({'answers':{'candidate_0':answer('none'),'completion_0':dict(type='choice',choice='invented',confidence=1,probabilities={'invented':1})}})
        with self.assertRaises(ValueError):await self.app.extract(ids)
        self.assertEqual(self.app.store.tasks()[0]['status'],'open')

    async def test_existing_exact_task_is_not_resubmitted(self):
        ids=self.events(['Please test Bluetooth.'])
        self.app.store.add_task('Please test Bluetooth.')
        self.app.http=FakeHTTP({})
        self.assertEqual(await self.app.extract(ids),[])
        self.assertEqual(self.app.http.calls,[])


class DecisionValidationTests(unittest.TestCase):
    def test_bounds_candidates_and_keeps_quotes_extractive(self):
        text='\n'.join(f'Please handle request {index}.' for index in range(70))
        candidates=task_candidates([dict(id='source',text=text)],[])
        self.assertEqual(len(candidates),48)
        self.assertTrue(all(candidate['text'] in text for candidate in candidates))
        self.assertTrue(all(candidate['source_id']=='source' for candidate in candidates))
        candidate=task_candidates([dict(id='long',text='x'*400)],[])[0]
        self.assertEqual(len(candidate['text']),240)

    def test_never_stitches_different_speakers_sessions_or_long_gaps(self):
        def event(identity,text,speaker='stream:0',session='one',said=1000):
            return dict(id=identity,text=text,event=dict(speaker_turns=[dict(speaker_key=speaker)]),session_id=session,said_at=said)
        first=event('a','I need to submit')
        for second in [event('b','a paper tomorrow at 5PM.',speaker='stream:1',said=1004),
                       event('b','a paper tomorrow at 5PM.',session='two',said=1004),
                       event('b','a paper tomorrow at 5PM.',said=1040)]:
            candidates=task_candidates([first,second],[])
            self.assertFalse(any('source_spans' in candidate for candidate in candidates))

    def test_multispeaker_event_continues_only_its_last_speaker(self):
        first=dict(id='a',text='Can you show an example? Yes. I need to submit',said_at=1000,session_id='one',
                   event=dict(speaker_turns=[dict(speaker_key='stream:1',text='Can you show an example?'),
                                             dict(speaker_key='stream:0',text='Yes. I need to submit')]))
        second=dict(id='b',text='a paper this Wednesday at 5PM.',said_at=1004,session_id='one',
                    event=dict(speaker_turns=[dict(speaker_key='stream:0',text='a paper this Wednesday at 5PM.')]))
        candidates=task_candidates([first,second],[])
        self.assertIn('I need to submit a paper this Wednesday at 5PM.',[c['text'] for c in candidates])

    def test_pickup_continuation_keeps_uncertain_date_tail(self):
        first=dict(id='a',text='I need to pick up my',said_at=1000,session_id='one',
                   event=dict(speaker_turns=[dict(speaker_key='stream:0',text='I need to pick up my')]))
        second=dict(id='b',text='grandma from the airport on Saturday.',said_at=1003,session_id='one',
                    event=dict(speaker_turns=[dict(speaker_key='stream:0',text='grandma from the airport'),
                        dict(speaker_key='stream:1',text='on Saturday.',voice_identity={'status':'uncertain'})]))
        candidates=task_candidates([first,second],[])
        self.assertEqual(candidates[0]['text'],'I need to pick up my grandma from the airport on Saturday.')
        self.assertEqual(len(candidates[0]['source_spans']),2)
        second['event']['speaker_turns'][1]['text']='I am going shopping.'
        second['text']='grandma from the airport I am going shopping.'
        self.assertFalse(any('source_spans' in c for c in task_candidates([first,second],[])))

    def test_rejects_invalid_choice_confidence_or_probability_distribution(self):
        for changed in [{'choice':'book_calendar_now'},{'confidence':True},{'confidence':2},{'probabilities':{'todo':1}}, {'probabilities':dict(todo=.8,none=.8,calendar=.2,action_item=.2)}]:
            with self.subTest(changed=changed),self.assertRaises(ValueError):task_answer({**answer('todo'),**changed})

    def test_old_database_migrates_in_place_preserving_tasks_and_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'old.db';db=sqlite3.connect(path)
            db.executescript("""
                CREATE TABLE sessions(id TEXT PRIMARY KEY,title TEXT,started_at REAL);
                INSERT INTO sessions VALUES('session','Original session',1000);
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO metadata VALUES('current_session','session');
                CREATE TABLE tasks(id TEXT PRIMARY KEY,session_id TEXT,title TEXT,status TEXT,
                    priority TEXT,owner TEXT,source_id TEXT,quote TEXT,created_at REAL,deleted INTEGER DEFAULT 0);
                INSERT INTO tasks VALUES('task','session','Existing task','done','normal',NULL,NULL,NULL,1001,0);
            """);db.close()
            store=Workspace(path)
            try:
                self.assertEqual(store.current,'session')
                task=store.tasks()[0]
                self.assertEqual((task['id'],task['title'],task['status']),('task','Existing task','done'))
                self.assertEqual(task['kind'],'todo')
                self.assertIsNone(task['decision_model'])
                self.assertIsNone(task['decision_confidence'])
                new=store.add_task('Manual addition')
                self.assertEqual(new['kind'],'todo')
            finally:store.db.close()
            reopened=Workspace(path)
            try:self.assertEqual(len(reopened.tasks()),2)
            finally:reopened.db.close()


if __name__=='__main__':unittest.main()
