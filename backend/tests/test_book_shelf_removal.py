from hashlib import sha256

import pytest

from agent.app_actions.knowledge_sources import KnowledgeSourceActionService
from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.knowledge.book_library import BookLibrary
from agent.knowledge.book_upload import prepare_book_upload
from test_book_library_api import library_client, _epub_bytes


def _runtime(core, user_id="tenant-a"):
    service=KnowledgeSourceActionService(book_library_provider=lambda:BookLibrary(core,user_id))
    return AppActionRuntime(knowledge_source_handler=service.execute)


def _confirm(runtime, book_id):
    request=AppActionRequest(action_id="book.remove",arguments={"import_id":book_id})
    context=AppActionContext(source="ui")
    review=runtime.dispatch(request,context)
    assert review.status=="confirmation_required"
    return runtime.confirm(review.confirmation.token,request,context)


def test_remove_requires_confirmation_hides_reads_and_retrieval_and_reimport_restores_progress(library_client):
    client,core,_=library_client
    library=BookLibrary(core,"tenant-a")
    content=_epub_bytes()
    book=library.import_epub(filename="book.epub",content=content,rights_attestation_version="",scan_approved=False,local_only=True)["book"]
    library.save_reader_progress(book["id"],.73)
    records=core.store.list_active_book_materialization_records(user_id="tenant-a")
    assert len(records)==1
    _,asset=library._source(book["id"])
    source=core.store.blobs.resolve(asset["blob_path"])
    digest=sha256(source.read_bytes()).hexdigest()
    runtime=_runtime(core)
    context=AppActionContext(source="ui")
    request=AppActionRequest(action_id="book.remove",arguments={"import_id":book["id"]})
    review=runtime.dispatch(request,context)
    assert review.status=="confirmation_required"
    assert library.list(limit=40,offset=0)["total"]==1
    receipt=runtime.confirm(review.confirmation.token,request,context)
    assert receipt.status=="applied" and receipt.result["changed"] is True
    assert library.list(limit=40,offset=0)["total"]==0
    assert core.store.list_active_book_materialization_records(user_id="tenant-a")==[]
    with pytest.raises(KeyError):
        core.store.get_active_book_materialization_record(user_id="tenant-a",edition_id=records[0]["edition_id"])
    for suffix in ("","/reader","/reader/full","/cover"):
        assert client.get(f'/api/knowledge/core/books/library/{book["id"]}{suffix}').status_code==404
    assert source.exists() and sha256(source.read_bytes()).hexdigest()==digest
    repeated=_confirm(runtime,book["id"])
    assert repeated.status=="applied" and repeated.result["changed"] is False
    _,repacked=prepare_book_upload("new-name.epub",content,title="A different package title")
    restored=library.import_epub(filename="new-name.epub",content=repacked,rights_attestation_version="",scan_approved=False,local_only=True,defer_processing=True)
    assert restored["restored"] is True and restored["book"]["id"]==book["id"]
    assert restored["book"]["reader_progress"]==.73
    assert library.list(limit=40,offset=0)["total"]==1
    assert len(core.store.list_active_book_materialization_records(user_id="tenant-a"))==1


def test_removal_is_tenant_scoped_and_confirmation_is_bound_to_the_selected_book(library_client):
    _,core,_=library_client
    library=BookLibrary(core,"tenant-a")
    book=library.import_epub(filename="book.epub",content=_epub_bytes(),rights_attestation_version="",scan_approved=False,local_only=True)["book"]
    other=_confirm(_runtime(core,"tenant-b"),book["id"])
    assert other.status!="applied"
    runtime=_runtime(core)
    context=AppActionContext(source="ui")
    request=AppActionRequest(action_id="book.remove",arguments={"import_id":book["id"]})
    review=runtime.dispatch(request,context)
    changed_request=AppActionRequest(action_id="book.remove",arguments={"import_id":"a-different-book"})
    assert runtime.confirm(review.confirmation.token,changed_request,context).status!="applied"
    assert library.list(limit=40,offset=0)["total"]==1
