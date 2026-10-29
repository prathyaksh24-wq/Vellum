import asyncio
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import wave

from fastapi.testclient import TestClient
import pytest

from agent import api
from agent.contracts.voice import DictationStatus, DictationTranscript
from agent.voice.session import VoiceEvent, VoiceSessionError, WhisperDictationSession
from agent.voice.dictation_models import MODELS, model_identity


@pytest.mark.parametrize('name',['small','large-v3-turbo'])
def test_selected_model_identity_reaches_status_and_worker_environment(tmp_path,name):
    root=tmp_path/('whisper-'+name)
    root.mkdir()
    settings=api.get_settings().model_copy(update={'dictation_model_dir':root})
    session=WhisperDictationSession(settings)
    session.python_executable.parent.mkdir(parents=True)
    session.python_executable.touch()
    for filename in ('model.bin','config.json','tokenizer.json'):
        (root/filename).touch()
    assert session.status().model==MODELS[name]['model_id']
    assert session.worker_environment['VELLUM_DICTATION_MODEL_ID']==MODELS[name]['model_id']
    assert MODELS[name]['label'] in session.status().detail
    renamed=tmp_path/'custom-model'
    renamed.mkdir()
    (renamed/'source.json').write_text(json.dumps(MODELS[name]),encoding='utf-8')
    assert model_identity(renamed)==(MODELS[name]['model_id'],MODELS[name]['label'])


def test_unrecognized_local_weights_do_not_claim_to_be_turbo(tmp_path):
    (tmp_path/'source.json').write_text('{broken',encoding='utf-8')
    assert model_identity(tmp_path)==('local/whisper','Local Whisper')


@pytest.mark.parametrize('features',[80,128])
def test_worker_warmup_supports_small_and_large_v3_audio_features(monkeypatch,tmp_path,features):
    import numpy as np
    worker_path=Path(__file__).parents[1]/'agent/voice/whisper_worker.py'
    monkeypatch.syspath_prepend(str(worker_path.parent))
    spec=importlib.util.spec_from_file_location('dictation_worker_test',worker_path)
    worker=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    encoded=[]
    class Model:
        feature_extractor=SimpleNamespace(mel_filters=np.zeros((features,201)))
        def __init__(self,*args,**kwargs):
            assert kwargs['local_files_only'] is True
        def encode(self,value):
            assert value.shape==(features,3000)
            encoded.append(value.shape)
    monkeypatch.setitem(sys.modules,'ctranslate2',SimpleNamespace())
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Model))
    monkeypatch.setenv('VELLUM_DICTATION_MODEL_DIR',str(tmp_path))
    monkeypatch.setenv('VELLUM_DICTATION_DEVICE','cpu')
    monkeypatch.setenv('PATH',__import__('os').environ.get('PATH',''))
    model,device,handles=worker.load_model()
    for handle in handles: handle.close()
    assert device=='cpu' and encoded==[(features,3000)]


def wav(seconds=0.1):
    target = BytesIO()
    with wave.open(target, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * int(seconds * 16000))
    return target.getvalue()


class Session:
    def __init__(self, *, available=True, error=False):
        self.available = available
        self.error = error
        self.calls = []

    def status(self):
        return DictationStatus(enabled=True, available=self.available, ready=self.available,
                               state="ready" if self.available else "unavailable", device="cpu", detail="Install local Whisper.")

    def prepare(self):
        if not self.available:
            raise VoiceSessionError("Install local Whisper.")
        return self.status()

    async def transcribe(self, audio, *, duration_seconds,language=None,dictionary=None):
        self.calls.append(audio)
        if self.error:
            raise VoiceSessionError("Transcription failed.")
        return DictationTranscript(text="A dictated draft.", language="en", duration_seconds=duration_seconds, device="cpu")


@pytest.fixture
def history_store(monkeypatch,tmp_path):
    from agent.voice.history import DictationStore
    store=DictationStore(tmp_path/'dictation.db')
    monkeypatch.setattr(api,'get_dictation_store',lambda:store)
    return store


@pytest.fixture(autouse=True)
def isolated_history(history_store):
    return history_store


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "start_scheduler", lambda: None)
    monkeypatch.setattr(api, "start_vault_watcher", lambda: None)
    with TestClient(api.app) as client:
        yield client


def test_dictation_returns_draft_text_without_running_the_chat_agent(client, monkeypatch):
    session = Session()
    monkeypatch.setattr(api, "get_dictation_session", lambda: session)
    def unexpected(*args, **kwargs):
        pytest.fail("Dictation must not invoke an agent turn.")
    monkeypatch.setattr(api, "_stream_agent_turn", unexpected)
    result = client.post("/api/voice/dictation/transcribe", files={"audio": ("voice.wav", wav(), "audio/wav")})
    assert result.status_code == 200
    data=result.json()
    assert data.pop('history_id')
    assert data == {"text": "A dictated draft.", "language": "en", "duration_seconds": 0.1,
                   "device": "cpu", "model": "openai/whisper-large-v3-turbo", "local": True,
                   "requested_language":"auto","history_error":None}
    assert len(session.calls) == 1
    assert client.get("/api/voice/dictation/status").json()["device"] == "cpu"
    history=client.get('/api/voice/dictation/history').json()
    assert history['items'][0]['text']=='A dictated draft.'


def test_kannada_override_reaches_transcription_instead_of_auto_tamil(client,monkeypatch):
    seen=[]
    class HintSession(Session):
        async def transcribe(self,audio,*,duration_seconds,language=None,dictionary=None):
            seen.append(language)
            return DictationTranscript(text='Kannada test' if language=='kn' else 'Tamil test',
                language=language or 'ta',duration_seconds=duration_seconds,device='cpu')
    monkeypatch.setattr(api,'get_dictation_session',lambda:HintSession())
    response=client.post('/api/voice/dictation/transcribe',data={'language':'kn'},files={'audio':('a.wav',wav(),'audio/wav')})
    assert response.status_code==200
    assert response.json()['language']=='kn'
    assert seen==['kn']


def test_saved_preferences_apply_to_uploads_and_history_can_be_disabled(client,monkeypatch,history_store):
    session=Session()
    monkeypatch.setattr(api,'get_dictation_session',lambda:session)
    def settings(patch):
        response=client.post('/api/app-actions/dispatch',json={'request':{'action_id':'dictation.settings.update','arguments':{'patch':patch}},'context':{'source':'ui'}})
        assert response.status_code==200 and response.json()['status']=='applied'
    settings({'language':'kn'})
    assert client.get('/api/voice/dictation/preferences').json()['settings']['language']=='kn'
    first=client.post('/api/voice/dictation/transcribe',files={'audio':('a.wav',wav(),'audio/wav')}).json()
    assert first['requested_language']=='kn' and first['history_id']
    settings({'save_history':False})
    second=client.post('/api/voice/dictation/transcribe',files={'audio':('a.wav',wav(),'audio/wav')}).json()
    assert second['history_id'] is None and second['history_error'] is None
    assert history_store.history().total==1


def test_bad_language_is_rejected_before_model_use(client,monkeypatch,history_store):
    session=Session()
    monkeypatch.setattr(api,'get_dictation_session',lambda:session)
    response=client.post('/api/voice/dictation/transcribe',data={'language':'xx'},files={'audio':('a.wav',wav(),'audio/wav')})
    assert response.status_code==422 and not session.calls and history_store.history().total==0


def test_history_storage_failure_does_not_lose_transcribed_text(client,monkeypatch,history_store):
    monkeypatch.setattr(api,'get_dictation_session',lambda:Session())
    def fail(*args):raise OSError('Storage unavailable')
    monkeypatch.setattr(history_store,'save',fail)
    response=client.post('/api/voice/dictation/transcribe',files={'audio':('a.wav',wav(),'audio/wav')})
    assert response.status_code==200 and response.json()['text']=='A dictated draft.'
    assert response.json()['history_id'] is None and response.json()['history_error']


@pytest.mark.parametrize("audio,expected", [(b"invalid", 400), (wav(300.1), 413), (b"x" * (15 * 1024 * 1024 + 1), 413)], ids=["invalid-wav", "too-long", "too-large"])
def test_invalid_or_excessive_audio_does_not_reach_model(client, monkeypatch, audio, expected):
    session = Session()
    monkeypatch.setattr(api, "get_dictation_session", lambda: session)
    response = client.post("/api/voice/dictation/transcribe", files={"audio": ("voice.wav", audio, "audio/wav")})
    assert response.status_code == expected
    assert session.calls == []


def test_unavailable_and_failed_models_report_errors_without_fake_transcripts(client, monkeypatch):
    session = Session(available=False)
    monkeypatch.setattr(api, "get_dictation_session", lambda: session)
    assert client.post("/api/voice/dictation/prepare").status_code == 503
    assert client.post("/api/voice/dictation/transcribe", files={"audio": ("a.wav", wav(), "audio/wav")}).status_code == 503
    assert not session.calls
    session.available = True
    session.error = True
    assert client.post("/api/voice/dictation/transcribe", files={"audio": ("a.wav", wav(), "audio/wav")}).status_code == 503


def test_installation_is_distinct_from_worker_readiness(tmp_path):
    settings = api.get_settings().model_copy(update={"dictation_model_dir": tmp_path, "dictation_device": "cpu", "voice_enabled": True})
    session = WhisperDictationSession(settings)
    assert not session.status().available
    python = session.python_executable
    python.parent.mkdir(parents=True)
    python.touch()
    assert not session.status().available
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (tmp_path / name).touch()
    assert session.status().available
    assert not session.status().ready
    session._ready = True
    session._process = SimpleNamespace(returncode=None)
    session._worker_metadata = {"device": "cpu"}
    assert session.status().ready
    assert session.status().device == "cpu"


@pytest.mark.asyncio
async def test_disconnect_cancels_active_transcription(monkeypatch):
    cancelled = asyncio.Event()
    class SlowSession(Session):
        async def transcribe(self, *args, **kwargs):
            try:
                await asyncio.sleep(100)
            finally:
                cancelled.set()
    class Disconnect:
        async def is_disconnected(self):
            await asyncio.sleep(0)
            return True
    from starlette.datastructures import UploadFile
    monkeypatch.setattr(api, "get_dictation_session", lambda: SlowSession())
    with pytest.raises(api.HTTPException) as exc:
        await api.dictation_transcribe(Disconnect(), UploadFile(BytesIO(wav()), filename="a.wav"))
    assert exc.value.status_code == 499
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_transcription_requires_a_terminal_transcript(monkeypatch):
    session = WhisperDictationSession()
    async def stream(*args, **kwargs):
        yield VoiceEvent("completed", {})
    monkeypatch.setattr(session, "stream_turn", stream)
    with pytest.raises(VoiceSessionError, match="no transcript"):
        await session.transcribe(wav(), duration_seconds=0.1)


def test_download_is_exact_audio_and_deleted_or_old_entries_have_no_recording(client,monkeypatch,history_store):
    monkeypatch.setattr(api,'get_dictation_session',lambda:Session())
    audio=wav()
    response=client.post('/api/voice/dictation/transcribe',files={'audio':('a.wav',audio,'audio/wav')})
    identity=response.json()['history_id']
    assert history_store.history().items[0].has_recording
    download=client.get(f'/api/voice/dictation/history/{identity}/recording')
    assert download.status_code==200 and download.content==audio
    assert download.headers['content-type']=='audio/wav'
    assert download.headers['cache-control']=='no-store'
    history_store.delete(entry_id=identity)
    assert client.get(f'/api/voice/dictation/history/{identity}/recording').status_code==404
    assert client.get('/api/voice/dictation/history/bad-id/recording').status_code==404


def test_saved_dictionary_reaches_the_same_transcription_worker_without_a_prompt_dropdown(client,monkeypatch,history_store):
    seen=[]
    class DictionarySession(Session):
        async def transcribe(self,audio,*,duration_seconds,language=None,dictionary=None):
            seen.append((language,dictionary))
            return await super().transcribe(audio,duration_seconds=duration_seconds,language=language,dictionary=dictionary)
    monkeypatch.setattr(api,'get_dictation_session',lambda:DictionarySession())
    history_store.update_preferences({'language':'kn','dictionary':['Vellum','ಕನ್ನಡ']})
    result=client.post('/api/voice/dictation/transcribe',files={'audio':('a.wav',wav(),'audio/wav')})
    assert result.status_code==200 and seen==[('kn',['Vellum','ಕನ್ನಡ'])]
