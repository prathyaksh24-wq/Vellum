"""Saved upload questions must not fall through to public search."""
import pytest
from agent.agents.youtube import YoutubeAgent
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService


@pytest.mark.parametrize('question',[
    'what did ohnepixel uploaded yesterday',
    'what did ohnePixel upload yesterday?',
    'show uploads from ohnepixel yesterday',
])
def test_creator_upload_day_uses_saved_records_without_search(tmp_path, question):
    calls=[]
    service=YoutubeCapabilityService(vault_root=tmp_path,
        search_backend=lambda *_: pytest.fail('Saved upload question reached public search'))
    service.subscription_feed=lambda payload: calls.append(payload) or {
        'configured':True,'uploads':[{'video_id':'abcdefghijk','title':'Saved upload title','creator':'ohnepixel raw',
            'channel_id':'UC'+'a'*22,'url':'https://www.youtube.com/watch?v=abcdefghijk','published_at':'2026-10-11T12:00:00Z'}],
        'date':'2026-10-11','timezone':'Asia/Kolkata','coverage':'Saved uploads only; feed coverage may be incomplete.'}
    agent=YoutubeAgent(vault_root=tmp_path,youtube_service=service,
        planner=lambda *_: {'source':'public'})
    response=agent.answer_with_context(question,{})
    assert response.status=='answered'
    assert 'Saved upload title' in response.summary
    assert 'https://www.youtube.com/watch?v=abcdefghijk' in response.summary
    assert calls==[{'limit':20,'creator':'ohnepixel','day_label':'Yesterday'}]
