"""Folder membership, persistence and revision-bound destructive actions."""
import json

from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.conversations.lifecycle import ConversationLifecycle


def setup(tmp_path):
    owner = ConversationLifecycle(path=tmp_path / 'conversations.json')
    owner.save('chat', {'title': 'Chat', 'messages': [{'role': 'user', 'text': 'Keep me'}]})
    runtime = AppActionRuntime(conversation_lifecycle=owner)
    context = AppActionContext(source='ui', invocation_conversation_id='chat')
    def dispatch(action, **arguments):
        return runtime.dispatch(AppActionRequest(action_id=action, arguments=arguments), context)
    return owner, runtime, context, dispatch


def test_project_catalog_survives_saves_and_reload(tmp_path):
    owner, _, _, dispatch = setup(tmp_path)
    created = dispatch('project.create', name='  Research  notes ')
    assert created.status == 'applied', created
    project = created.result['project']
    assert project['name'] == 'Research notes'
    owner.save('another', {'title': 'Other', 'messages': []})
    owner.replace_all(owner.list())
    assert ConversationLifecycle(path=owner.path).projects() == [project]


def test_membership_undo_and_stale_autosave(tmp_path):
    owner, runtime, context, dispatch = setup(tmp_path)
    project = dispatch('project.create', name='Research').result['project']
    stale = owner.get('chat')
    moved = dispatch('conversation.project.set', conversation_id='chat', project_id=project['id'], target_revision=0)
    assert moved.status == 'applied', moved
    owner.save('chat', {**stale, 'messages': [*stale['messages'], {'role': 'assistant', 'text': 'Done'}]})
    assert owner.get('chat')['projectId'] == project['id']
    # An unrelated later write makes undo stale instead of losing the message.
    assert runtime.undo(moved.undo.token, context).status == 'failed'
    removed = dispatch('conversation.project.set', conversation_id='chat', project_id=None)
    assert removed.status == 'applied'
    assert runtime.undo(removed.undo.token, context).status == 'undone'
    assert owner.get('chat')['projectId'] == project['id']


def test_invalid_membership_does_not_mutate(tmp_path):
    owner, _, _, dispatch = setup(tmp_path)
    before = owner.path.read_bytes()
    assert dispatch('conversation.project.set', conversation_id='chat', project_id='missing').status == 'failed'
    assert owner.path.read_bytes() == before


def test_folder_removal_refreshes_existing_conversation_projections(tmp_path):
    projected = []
    owner = ConversationLifecycle(path=tmp_path/'conversations.json',
        projector=lambda chat: projected.append((chat['id'],chat.get('projectId'))) or {})
    project = owner.change_project('create', {'name':'Research'})['project']
    owner.save('chat', {'title':'Chat','projectId':project['id'],'messages':[]})
    projected.clear()
    owner.change_project('remove', {'project_id':project['id']})
    assert projected == [('chat',None)]


def test_new_project_chat_uses_normal_draft_navigation(tmp_path):
    owner, _, _, dispatch = setup(tmp_path)
    project = dispatch('project.create', name='Research').result['project']
    result = dispatch('conversation.new', project_id=project['id'])
    assert result.status == 'applied', result
    assert result.result['navigation'] == {'view': 'chat', 'conversation_id': None, 'project_id': project['id']}
    assert len(owner.list()) == 1


def test_remove_requires_confirmation_keeps_messages_and_rejects_stale(tmp_path):
    owner, runtime, context, dispatch = setup(tmp_path)
    project = dispatch('project.create', name='Research').result['project']
    dispatch('conversation.project.set', conversation_id='chat', project_id=project['id'])
    request = AppActionRequest(action_id='project.remove', arguments={'project_id': project['id']})
    pending = runtime.dispatch(request, context)
    assert pending.status == 'confirmation_required', pending
    dispatch('project.update', project_id=project['id'], patch={'name': 'Renamed'})
    assert runtime.confirm(pending.confirmation.token, request, context).status == 'failed'
    pending = runtime.dispatch(request, context)
    assert runtime.confirm(pending.confirmation.token, request, context).status == 'applied'
    assert owner.projects() == []
    assert owner.get('chat')['projectId'] is None
    assert owner.get('chat')['messages'][0]['text'] == 'Keep me'
    assert json.loads(owner.path.read_text())['projects'] == []
