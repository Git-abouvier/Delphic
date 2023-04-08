from typing import List
from ninja import Router, File, NinjaAPI, Form
from ninja.files import UploadedFile
from django.conf import settings
from django.http import HttpRequest
from django.core.files.base import ContentFile

from chat_all_the_docs.utils.collections import query_collection
from .auth.api_key import NinjaApiKeyAuth
from asgiref.sync import sync_to_async
from .ninja_types import CollectionIn, CollectionModelSchema, CollectionQueryOutput, CollectionQueryInput
from chat_all_the_docs.indexes.models import Document, Collection
from chat_all_the_docs.tasks import create_index

collections_router = Router()

api = NinjaAPI(
    title="GREMLIN Engine NLP Microservice",
    description="Chat-All-The-Docs is a LLM document model orchestration engine that makes it easy to vectorize a "
                "collection of documents and then build and serve discrete Llama-Index models for each collection to "
                "create bespoke, highly-targed chattable knowledge bases.",
    version="b0.9.0",
    auth=None if settings.OPEN_ACCESS_MODE else NinjaApiKeyAuth(),
)

api.add_router("/collections", collections_router)


@api.get(
    "/heartbeat",
    auth=None,
    response=bool,
    tags=["Misc"],
    summary="Return true if api is up and running.",
)
def check_heartbeat(request):
    return True


@collections_router.post("/create")
async def create_collection(request, collection_data: CollectionIn = Form(...), files: List[UploadedFile] = File(...)):
    key = None if getattr(request, "auth", None) is None else request.auth
    if key is not None:
        key = await key
    print(f"API KEY: {key}")

    collection_instance = Collection(
        api_key=key,
        title=collection_data.title,
        description=collection_data.description,
        status=collection_data.status,
    )

    await sync_to_async(collection_instance.save)()

    for uploaded_file in files:
        doc_data = uploaded_file.file.read()
        doc_file = ContentFile(doc_data, uploaded_file.name)
        document = Document(collection=collection_instance, file=doc_file)
        await sync_to_async(document.save)()

    create_index.si(collection_instance.id).apply_async()

    # result = await sync_to_async(CollectionModelSchema.from_orm)(collection_instance)
    return await sync_to_async(CollectionModelSchema)(
        id=collection_instance.id,
        title=collection_instance.title,
        description=collection_instance.description,
        status=collection_instance.status,
        created=collection_instance.created.isoformat(),
        modified=collection_instance.modified.isoformat(),
    )


@collections_router.post("/query", response=CollectionQueryOutput, summary="Ask a question of a document collection")
def query_collection_view(request: HttpRequest, query_input: CollectionQueryInput):
    collection_id = query_input.collection_id
    query_str = query_input.query_str
    response = query_collection(collection_id, query_str)
    return {"response": response}


@collections_router.get("/available", response=List[CollectionModelSchema],
                        summary="Get a list of all of the collections "
                                "created with my api_key")
async def get_my_collections_view(request: HttpRequest):
    key = None if getattr(request, "auth", None) is None else request.auth
    if key is not None:
        key = await key
    print(f"API KEY: {key}")

    collections = Collection.objects.filter(api_key=key)

    return [{"id": collection.id,
             "title": collection.title,
             "description": collection.description,
             "status": collection.status,
             "created": collection.created.isoformat(),
             "modified": collection.modified.isoformat()} async for collection in collections]