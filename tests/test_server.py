import re
import time

from fastapi.testclient import TestClient

from coach.server import create_app, Offer, VOICE_NAMES


def headers(client):
    html=client.get("/").text
    token=re.search(r'name="coach-token" content="([^"]+)"',html).group(1)
    return {"X-Coach-Token":token}


def test_local_api_mode_switch_and_key_is_never_returned(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY",raising=False)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        h=headers(client)
        assert client.get('/api/config').json()['key_configured'] is False
        assert client.post('/api/mode',json={'mode':'demo'}).status_code==403
        assert client.post('/api/mode',headers={**h,'Origin':'https://evil.example'},json={'mode':'demo'}).status_code==403
        assert client.post('/api/mode',headers=h,json={'mode':'demo'}).status_code==200
        time.sleep(.1)
        state=client.get('/api/state').json()
        assert state['telemetry']['source']=='demo'
        assert state['telemetry']['status']=='live'
        assert client.post('/api/key',headers=h,json={'api_key':'test-key-not-real'}).status_code==200
        config=client.get('/api/config').text
        assert 'test-key-not-real' not in config
        assert client.get('/api/export').headers['content-disposition'].startswith('attachment')


def test_missing_key_fails_before_external_voice_request(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        result=client.post('/api/live/session',headers=headers(client),json={'sdp':'fake-sdp-for-test'})
        assert result.status_code==503


def test_live_wire_contract_with_mocked_openai(tmp_path,monkeypatch):
    import httpx
    from coach import server
    monkeypatch.setenv('OPENAI_API_KEY','test-local-key')
    requests=[]
    class FakeClient:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,url,**kwargs):
            requests.append((url,kwargs))
            return httpx.Response(201,json={'session':{'id':'live_test'},'transport':{'type':'webrtc','sdp':'test-answer'}})
    monkeypatch.setattr(server.httpx,'AsyncClient',FakeClient)
    with TestClient(create_app(data_dir=tmp_path)) as client:
        h=headers(client)
        response=client.post('/api/live/session',headers=h,json={'sdp':'test-offer-sdp','voice':'quartz'})
        assert response.status_code==200
        assert response.json()['transport']['sdp']=='test-answer'
        url,payload=requests[0]
        assert url=='https://api.openai.com/v1/live/sessions'
        assert payload['json']['session']['model']=='gpt-live-1'
        assert payload['json']['session']['audio']['output']['voice']=='quartz'
        assert payload['json']['session']['delegation']=={'type':'client'}
        instructions=payload['json']['session']['instructions']
        from pathlib import Path
        import json
        catalog=json.loads((Path(__file__).resolve().parent.parent/'web'/'engineer-personality.json').read_text(encoding='utf-8'))
        assert instructions=='\n\n'.join(catalog['instructions'])
        assert 'calm, friendly teammate' in instructions
        assert set(Offer.model_fields)=={'sdp','voice'}
        assert 'Interruption policy:' in payload['json']['session']['instructions']
        assert payload['json']['transport']=={'type':'webrtc','sdp':'test-offer-sdp'}
        assert client.post('/api/live/session',headers=h,json={'sdp':'test-offer-sdp'}).status_code==409
        assert client.post('/api/live/close/live_test',headers=h,json={'confirmed':True}).status_code==200


def test_removed_personality_routes_and_saved_choices_are_not_used(tmp_path):
    (tmp_path/'personality.json').write_text('{"version":1,"personality":"legacy-mode"}',encoding='utf-8')
    with TestClient(create_app(data_dir=tmp_path)) as client:
        assert client.get('/api/personality').status_code==404
        assert client.post('/api/personality',headers=headers(client),json={'personality':'legacy-mode'}).status_code==404
        assert (tmp_path/'personality.json').is_file()  # Local files are left intact.


def test_voice_catalog_matches_selection_and_rejects_unknown_names():
    from pathlib import Path
    import pytest
    from pydantic import ValidationError
    html=(Path(__file__).resolve().parent.parent/'web'/'index.html').read_text(encoding='utf-8')
    select=re.search(r'<select id="voice">(.*?)</select>',html).group(1)
    assert tuple(re.findall(r'<option value="([^"]+)"',select))==VOICE_NAMES
    assert len(set(VOICE_NAMES))==31
    for voice in VOICE_NAMES:
        assert Offer(sdp='test-offer-sdp',voice=voice).voice==voice
    with pytest.raises(ValidationError):
        Offer(sdp='test-offer-sdp',voice='unknown-voice')


def test_display_choices_persist_across_app_restarts_and_require_local_token(tmp_path):
    choices={'version':1,'preset':'custom','order':'race','density':'compact','transparent':True,
             'opacity':85,'widgets':{'map':False,'race':True},'parts':{'volume':True},'collapsed':{'race':True}}
    with TestClient(create_app(data_dir=tmp_path)) as client:
        assert client.get('/api/display').json() is None
        assert client.post('/api/display',json=choices).status_code==403
        assert client.post('/api/display',headers=headers(client),json=choices).status_code==200
    with TestClient(create_app(data_dir=tmp_path)) as client:
        assert client.get('/api/display').json()==choices
