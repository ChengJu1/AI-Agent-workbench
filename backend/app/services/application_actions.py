"""Agent-facing ledger tools. The Agent reads pages and drafts; values come from a reviewed profile version,
what the user said in chat, or the Agent's own flagged drafts. Nothing here writes to an employer's site.
"""
from app.errors import ServiceError
from app.models.applications import ApplicationRef, ApplicationSave, ApplicationSaveArgs, PrepareKitArgs, ReadFormArgs
from app.storage.application_store import FIELDS
from app.storage.profile_store import resolve

FLAGS = {'inferred': 'draft', 'user': 'chat'}


class ApplicationActions:
    def __init__(self, applications, profiles, platform):
        self.applications, self.profiles, self.platform = applications, profiles, platform
        self.forms = {}  # (conversation, session) -> last read form; kit items refer to its field keys.

    def dispatch(self, conversation_id, name, arguments):
        if name == 'application_list':
            return {'applications': self.applications.list()}
        if name == 'application_read':
            return self.applications.get(ApplicationRef.model_validate(arguments).application_id)
        if name == 'application_save':
            return self.save(ApplicationSaveArgs.model_validate(arguments))
        if name == 'application_profiles':
            return self.profiles_for_kit()
        if name == 'application_read_form':
            return self.read_form(conversation_id, ReadFormArgs.model_validate(arguments).session_id)
        if name == 'application_prepare_kit':
            return self.prepare_kit(conversation_id, PrepareKitArgs.model_validate(arguments))
        raise ServiceError('台账工具不存在。', 404)

    def save(self, args):
        provided = args.model_dump(include=args.model_fields_set & set(FIELDS))
        if args.application_id is None:
            return self.applications.save(ApplicationSave(**provided), actor='agent', stage=args.stage)
        # The Agent updates only what it names; other fields keep their current values.
        current = self.applications.get(args.application_id)
        merged = ApplicationSave(**{**{f: current[f] for f in FIELDS}, **provided})
        return self.applications.save(merged, args.application_id, actor='agent', stage=args.stage)

    def profiles_for_kit(self):
        result = []
        for summary in self.profiles.list():
            if summary['reviewed_version']:
                profile = self.profiles.get(summary['id'], summary['reviewed_version'])
                result.append({'id': profile['id'], 'name': profile['name'], 'version': profile['version'], 'data': profile['data']})
        return {'profiles': result, 'notice': '只能使用用户审阅保存过的版本；资料没有的信息直接在对话中问用户，不要编造。'}

    def read_form(self, conversation_id, session_id):
        """Read-only: field names, sections, control types, required marks and current values. Never opens or clicks anything."""
        self.platform.require(conversation_id, 'browser')
        form = self.platform.browser.call('form_extract', conversation_id, session_id)
        self.forms[(conversation_id, session_id)] = form
        fields = [{k: f[k] for k in ('key', 'label', 'section', 'type', 'required', 'value', 'options', 'format') if f.get(k) not in (None, '', [])}
                  for f in form['fields'] if not f.get('disabled')]
        return {'url': form['url'], 'fields': fields, 'notice': '用 application_prepare_kit 为这些字段生成资料包（key + 来源）。平台不会填写页面，用户照资料包自己填写和提交。'}

    def prepare_kit(self, conversation_id, args):
        profile = self.profiles.reviewed(args.profile_id, args.profile_version)
        form = self.forms.get((conversation_id, args.session_id)) if args.session_id else None
        if args.session_id and form is None:
            raise ServiceError('请先用 application_read_form 读取当前表单。', 409)
        fields = {f['key']: f for f in (form or {}).get('fields', [])}
        items, covered = [], set()
        for item in args.items:
            field = fields.get(item.key) if item.key else None
            if item.key and field is None:
                raise ServiceError(f'字段 {item.key} 不在最近读取的表单中，请重新读取。', 409)
            covered.add(item.key)
            value, flag = self._value(conversation_id, profile, args.profile_version, item)
            items.append({'label': (field or {}).get('label') or item.label.strip(), 'section': (field or {}).get('section') or item.section,
                          'type': (field or {}).get('type', ''), 'required': bool((field or {}).get('required')),
                          'options': (field or {}).get('options', []), 'value': value, 'flag': flag, 'note': item.note,
                          'source': item.source.model_dump(mode='json'), 'transform': item.transform,
                          'order': list(fields).index(item.key) if field else len(fields) + len(items)})
        # Required fields the kit does not cover are listed too, so the user sees what is left to them.
        for key, field in fields.items():
            if field.get('required') and key not in covered and not field.get('disabled') and not field.get('value'):
                items.append({'label': field['label'], 'section': field.get('section', ''), 'type': field['type'], 'required': True,
                              'options': field.get('options', []), 'value': '', 'flag': 'missing', 'note': '资料中没有，请自行填写',
                              'source': {'kind': 'none', 'ref': ''}, 'transform': '', 'order': list(fields).index(key)})
        items.sort(key=lambda i: i['order'])
        for i in items:
            i.pop('order')
        kit = {'profile_id': args.profile_id, 'profile_version': args.profile_version, 'form_url': (form or {}).get('url', ''), 'items': items}
        saved = self.applications.save_kit(args.application_id, kit)
        missing = [i['label'] for i in items if i['flag'] == 'missing']
        return {'application_id': saved['id'], 'stage': saved['stage'], 'items': len(items), 'missing': missing,
                'notice': '资料包已保存在投递台账，用户在任务页逐项复制填写。不要声称已填写或已投递；用户提交后会自己在台账标记。'}

    def _value(self, conversation_id, profile, version, item):
        source = item.source
        if source.kind == 'profile':
            if source.version not in (None, version):
                raise ServiceError('资料来源版本必须与 profile_version 一致。', 409)
            if item.transform.startswith('option:'):
                return item.transform.split(':', 1)[1], 'converted'  # Fact mapped to a page option; shown as a conversion.
            return resolve(profile, source.ref, item.transform), ''
        if source.kind == 'file':
            self.platform.require(conversation_id, 'files')
            info = self.platform.files.validate_reference(conversation_id, source.ref)
            return info['filename'], 'file'
        return item.value.strip(), FLAGS[source.kind]
