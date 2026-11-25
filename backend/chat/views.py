import logging

from django.conf import settings
from django.db import transaction
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from agents.documents.embeddings import EmbeddingError
from agents.documents.indexing import embed_texts
from agents.documents.ingest import DocumentIngestError, extract_text, split_into_chunks
from agents.graph import run_chat
from agents.llm import LLMError

from .errors import ApiError
from .models import Conversation, Document, DocumentChunk, Message

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf": "pdf", ".txt": "txt"}


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000, trim_whitespace=True)
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    document_id = serializers.IntegerField(required=False, allow_null=True)


def _document_payload(document: Document) -> dict:
    return {
        "id": document.id,
        "name": document.name,
        "file_type": document.file_type,
        "char_count": document.char_count,
        "created_at": document.created_at,
    }


@api_view(["GET"])
def health(_request):
    return Response({"status": "ok"})


class DocumentListCreateView(APIView):
    def get(self, _request):
        return Response([_document_payload(d) for d in Document.objects.all()[:50]])

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            raise ApiError("No file provided. Send a PDF or TXT file in the 'file' field.")

        extension = "." + upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
        if extension not in ALLOWED_EXTENSIONS:
            raise ApiError("Unsupported file type. Please upload a PDF or TXT file.")
        if upload.size > settings.MAX_UPLOAD_BYTES:
            raise ApiError(f"File is too large (max {settings.MAX_UPLOAD_BYTES // 1024 // 1024} MB).", status=413)

        try:
            pages = extract_text(upload.read(), ALLOWED_EXTENSIONS[extension])
        except DocumentIngestError as error:
            raise ApiError(str(error), status=422)

        chunks = split_into_chunks(pages)
        if not chunks:
            raise ApiError("The document contains no readable text.", status=422)

        # Embed before opening the transaction: model inference must not hold a DB connection/lock, and a
        # failure here leaves nothing half-indexed.
        try:
            vectors = embed_texts([c.text for c in chunks])
        except EmbeddingError as error:
            logger.error("Embedding failed during upload: %s", error)
            raise ApiError(f"The embedding model is unavailable: {error}", status=503)

        with transaction.atomic():
            document = Document.objects.create(
                name=upload.name[:255],
                file_type=ALLOWED_EXTENSIONS[extension],
                char_count=sum(len(c.text) for c in chunks),
                embedding_model=settings.EMBEDDING_MODEL,
            )
            DocumentChunk.objects.bulk_create(
                [
                    DocumentChunk(document=document, index=c.index, page=c.page, heading=c.heading, text=c.text, embedding=vector)
                    for c, vector in zip(chunks, vectors)
                ]
            )
        return Response({**_document_payload(document), "chunks": len(chunks)}, status=201)


class DocumentDetailView(APIView):
    def delete(self, _request, pk):
        deleted, _ = Document.objects.filter(pk=pk).delete()
        if not deleted:
            raise ApiError("Document not found.", status=404)
        return Response(status=204)


class ChatView(APIView):
    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise ApiError("Invalid request: " + "; ".join(f"{k}: {v[0]}" for k, v in serializer.errors.items()))
        data = serializer.validated_data

        conversation = self._get_conversation(data.get("conversation_id"))
        document_id = data.get("document_id")
        if document_id and not Document.objects.filter(pk=document_id).exists():
            raise ApiError("The selected document no longer exists.", status=404)

        history = [
            {"role": m.role, "content": m.content}
            for m in conversation.messages.order_by("-created_at", "-id")[:6][::-1]
        ]
        Message.objects.create(conversation=conversation, role="user", content=data["message"])

        try:
            result = run_chat(message=data["message"], history=history, document_id=document_id)
        except LLMError as error:
            raise ApiError(f"The language model is unavailable: {error}", status=503)

        answer = result["answer"]
        Message.objects.create(
            conversation=conversation,
            role="assistant",
            content=answer,
            agent=result["agent"],
            blocks=result["blocks"],
        )
        return Response(
            {
                "conversation_id": str(conversation.id),
                "agent": result["agent"],
                "answer": answer,
                "blocks": result["blocks"],
                "tool_trace": result["tool_trace"],
            }
        )

    @staticmethod
    def _get_conversation(conversation_id):
        if conversation_id is None:
            return Conversation.objects.create()
        try:
            return Conversation.objects.get(pk=conversation_id)
        except Conversation.DoesNotExist:
            raise ApiError("Conversation not found.", status=404)


class ConversationMessagesView(APIView):
    def get(self, _request, conversation_id):
        if not Conversation.objects.filter(pk=conversation_id).exists():
            raise ApiError("Conversation not found.", status=404)
        messages = Message.objects.filter(conversation_id=conversation_id)
        return Response(
            [
                {"role": m.role, "content": m.content, "agent": m.agent, "blocks": m.blocks, "created_at": m.created_at}
                for m in messages
            ]
        )
