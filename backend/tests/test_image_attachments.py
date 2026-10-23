"""Image and scanned-PDF attachments reach the model inside the user message; nothing else changes."""
import asyncio
import base64
from dataclasses import replace
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from PIL import Image

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.errors import ServiceError
from app.platform.files import SCANNED_PDF, document_images, file_kind, parse_document
from app.runtime.context_summary import IMAGE_TOKENS, WorkbenchSummarizationMiddleware
from scripted_turn import ScriptedTurn


def picture(size=(64, 64), color=(255, 0, 0), kind='PNG'):
    data = io.BytesIO()
    Image.new('RGB', size, color).save(data, kind)
    return data.getvalue()


def scanned_pdf(pages=2):
    images = [Image.new('RGB', (200, 280), (40 * index, 80, 120)) for index in range(pages)]
    data = io.BytesIO()
    images[0].save(data, 'PDF', save_all=True, append_images=images[1:])
    return data.getvalue()


FAKE_IMAGE = {'mime': 'image/jpeg', 'data': base64.b64encode(b'synthetic-jpeg').decode()}


@unittest.skipUnless(os.getenv('WORKBENCH_RUN_SANDBOX_TESTS') == '1', 'Real parser subprocess needs host sandbox access')
class ImageWorkerTests(unittest.TestCase):
    def test_images_are_verified_and_downscaled_in_the_sandbox(self):
        self.assertIn('图片附件 64×64', parse_document('.png', picture()))
        self.assertIn('图片附件', parse_document('.jpg', picture(kind='JPEG')))
        with self.assertRaises(ServiceError):
            parse_document('.png', b'not an image')
        [image] = document_images('.png', picture(size=(3000, 1000)))
        decoded = Image.open(io.BytesIO(base64.b64decode(image['data'])))
        self.assertEqual((image['mime'], decoded.format, max(decoded.size)), ('image/jpeg', 'JPEG', 1568))

    def test_scanned_pdf_is_recognised_and_sent_as_page_images(self):
        text = parse_document('.pdf', scanned_pdf(3))
        self.assertTrue(text.startswith(SCANNED_PDF))
        self.assertIn('共 3 页', text)
        self.assertEqual(len(document_images('.pdf', scanned_pdf(3))), 3)


class ImageAttachmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.services = build_services(Settings(database_path=Path(temporary.name) / 'synthetic.db', deepagents_model='deepseek-v4-flash'))
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        created = self.client.post('/api/agents', json={'name': '合成看图助手', 'description': '合成', 'system_prompt': '看附件回答',
                                                      'platform_capabilities': ['files']}).json()
        self.agent = self.services.registry.get_agent(created['id'])
        self.cid = self.services.conversations.create(self.agent.id)
        self.model = ScriptedTurn(responses=['unused'], reply='看到了')
        self.services.deep_agents.model_factory = lambda: self.model

    def upload(self, filename, data, parsed, cid=None):
        with patch('app.platform.files.parse_document', return_value=parsed):
            response = self.client.post(f'/api/conversations/{cid or self.cid}/files', files={'file': (filename, data)})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def send(self, content, attachment_ids, images=(FAKE_IMAGE,)):
        with patch('app.platform.files.document_images', return_value=list(images)) as convert:
            response = self.client.post(f'/api/conversations/{self.cid}/messages/stream',
                                        json={'content': content, 'attachment_ids': attachment_ids})
        return response, convert

    def test_kinds_follow_the_suffix_and_the_scanned_pdf_note(self):
        self.assertEqual(file_kind('photo.PNG', ''), 'image')
        self.assertEqual(file_kind('scan.pdf', SCANNED_PDF + '，共 2 页'), 'scanned_pdf')
        self.assertEqual(file_kind('resume.pdf', 'Python SQL'), 'text')
        image = self.upload('photo.png', picture(), '[图片附件 64×64：……]')
        scan = self.upload('scan.pdf', scanned_pdf(), SCANNED_PDF + '，共 2 页……]')
        text = self.upload('notes.md', b'# notes', '# notes')
        self.assertEqual([image['kind'], scan['kind'], text['kind']], ['image', 'scanned_pdf', 'text'])

    def test_images_ride_in_the_user_message_and_stay_in_history(self):
        image = self.upload('photo.png', picture(), '[图片附件 64×64：……]')
        response, convert = self.send('图里是什么颜色？', [image['id']])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('看到了', response.text)
        convert.assert_called_once()
        latest = self.model.seen[0][-1]
        self.assertIsInstance(latest, HumanMessage)
        self.assertEqual(latest.content[0], {'type': 'text', 'text': '图里是什么颜色？'})
        self.assertIn(image['id'], latest.content[1]['text'])
        self.assertEqual(latest.content[2]['image_url']['url'], f"data:image/jpeg;base64,{FAKE_IMAGE['data']}")
        stored = self.client.get(f'/api/conversations/{self.cid}/messages').json()[0]
        self.assertEqual(stored['attachments'], [{'id': image['id'], 'filename': 'photo.png'}])
        self.client.post(f'/api/conversations/{self.cid}/messages/stream', json={'content': '再说一遍'})
        history = self.model.seen[-1]
        self.assertTrue(any(isinstance(m.content, list) and any(b.get('type') == 'image_url' for b in m.content) for m in history[:-1]))

    def test_unsupported_model_text_files_and_foreign_attachments_are_refused(self):
        image = self.upload('photo.png', picture(), '[图片附件 64×64：……]')
        text = self.upload('notes.md', b'# notes', '# notes')
        response, _ = self.send('看看', [text['id']])
        self.assertEqual(response.status_code, 422)
        self.assertIn('read_file', response.json()['detail'])
        other = self.services.conversations.create(self.agent.id)
        foreign = self.upload('other.png', picture(), '[图片附件 64×64：……]', cid=other)
        self.assertEqual(self.send('看看', [foreign['id']])[0].status_code, 404)
        self.assertEqual(self.send('看看', ['not-a-file-id'])[0].status_code, 422)
        self.assertEqual(self.send('看看', [image['id']] * 6)[0].status_code, 422)
        pro = replace(self.services.deep_agents.settings, deepagents_model='deepseek-v4-pro')
        with patch.object(self.services.deep_agents, 'settings', pro):
            response, convert = self.send('看看', [image['id']])
        self.assertEqual(response.status_code, 422)
        self.assertIn('deepseek-v4-flash', response.json()['detail'])
        convert.assert_not_called()
        self.assertEqual(self.services.store.get_messages(self.cid), [])  # Nothing is stored for a refused message.

    def test_compaction_counts_images_at_a_fixed_cost_and_archives_their_labels(self):
        middleware = WorkbenchSummarizationMiddleware(ScriptedTurn(responses=['unused']), self.services.deep_agents.settings,
                                                      directory=self.services.deep_agents.conversation_directory(self.cid))
        huge = base64.b64encode(os.urandom(600_000)).decode()
        message = HumanMessage(content=[{'type': 'text', 'text': '[附件 photo.png（file_x）]'},
                                        {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{huge}'}}])
        self.assertLess(middleware.count_messages([message]), IMAGE_TOKENS + 100)
        rewritten, failed = asyncio.run(middleware._aoffload_inline_media(None, [message]))
        self.assertFalse(failed)
        self.assertNotIn(huge, str(rewritten))
        self.assertIn('photo.png', str(rewritten))


if __name__ == '__main__':
    unittest.main()
