"""API local para probar la extracción de documentos de KORVIA."""

from __future__ import annotations

import hashlib
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from korvia.chat import ChatError, ChatSource, NO_EVIDENCE_ANSWER, get_chat_provider
from korvia.auth import (
    check_login_attempt,
    clear_login_failures,
    get_current_user,
    hash_password,
    issue_token,
    normalize_email,
    record_login_failure,
    require_owner_access,
    require_read_access,
    require_write_access,
    revoke_token,
    validate_email,
    verify_password,
)
from korvia.database import get_session, initialize_database
from korvia.embeddings import EmbeddingError, get_provider
from korvia.document_processing import (
    DocumentProcessingError,
    OCRProcessingError,
    OCRUnavailableError,
    SUPPORTED_EXTENSIONS,
    UnsupportedDocumentType,
    process_document,
)
from korvia.file_storage import remove_original, save_original
from korvia.search import current_version_number, find_similar_chunks
from korvia.sync import SyncError, collect_source_files
from korvia.models import (
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_OWNER,
    Agent,
    AgentRun,
    AuditEvent,
    Document,
    DocumentChunk,
    DocumentVersion,
    KnowledgeSpace,
    Membership,
    SyncedFile,
    SyncRun,
    Tenant,
    User,
    utc_now,
)


MAX_UPLOAD_BYTES = int(os.getenv("KORVIA_MAX_UPLOAD_BYTES", "25000000"))
MIN_ANSWER_SCORE = float(os.getenv("KORVIA_MIN_ANSWER_SCORE", "0.05"))
SYNC_ROOT = os.getenv("KORVIA_SYNC_ROOT", "").strip()
VALID_ROLES = {ROLE_ADMIN, ROLE_MEMBER}
VALID_METADATA_VALUES = (str, int, float, bool, type(None))


class DocumentError(RuntimeError):
    """Error de archivo que la API convierte en respuesta HTTP."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class VersionAlreadyExists(RuntimeError):
    """El archivo ya está guardado con ese contenido."""

    def __init__(self, document: Document) -> None:
        super().__init__("Esta versión ya está guardada.")
        self.document = document


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield


app = FastAPI(
    title="KORVIA — prototipo local",
    description="Extrae y versiona documentos empresariales con acceso controlado.",
    version="0.8.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    """Cabeceras básicas para evitar marcos ajenos y guardar respuestas."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


class ChunkResponse(BaseModel):
    index: int
    text: str
    sources: list[str]


class DocumentInspectionResponse(BaseModel):
    filename: str
    extraction_method: str
    block_count: int
    chunks: list[ChunkResponse]
    warnings: list[str]


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TenantResponse(BaseModel):
    id: str
    name: str
    created_at: datetime


class SpaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class SpaceResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    created_at: datetime


class StoredChunkResponse(BaseModel):
    position: int
    text: str
    sources: list[str]


class DocumentSummaryResponse(BaseModel):
    id: str
    tenant_id: str
    space_id: str
    filename: str
    file_extension: str
    content_sha256: str
    extraction_method: str
    warning_messages: list[str]
    metadata: dict[str, str | int | float | bool | None]
    chunk_count: int
    version_count: int
    created_at: datetime
    updated_at: datetime


class DocumentResponse(DocumentSummaryResponse):
    version: int
    deleted_at: datetime | None
    chunks: list[StoredChunkResponse]


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummaryResponse]


class VersionSummaryResponse(BaseModel):
    version_number: int
    filename: str
    content_sha256: str
    extraction_method: str
    warning_messages: list[str]
    created_at: datetime


class VersionListResponse(BaseModel):
    versions: list[VersionSummaryResponse]


class VersionResponse(BaseModel):
    version_number: int
    filename: str
    extraction_method: str
    warning_messages: list[str]
    created_at: datetime
    chunks: list[StoredChunkResponse]


class MetadataUpdateRequest(BaseModel):
    metadata: dict[str, str | int | float | bool | None]


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    company_name: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: str
    created_at: datetime


class SessionResponse(BaseModel):
    token: str
    user: UserResponse


class RegistrationResponse(SessionResponse):
    tenant: TenantResponse


class MembershipResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    role: str


class MeResponse(BaseModel):
    user: UserResponse
    memberships: list[MembershipResponse]


class AddMemberRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    role: str = Field(default=ROLE_MEMBER, max_length=20)


class MemberResponse(BaseModel):
    user_id: str
    email: str
    role: str
    created_at: datetime


class MemberListResponse(BaseModel):
    members: list[MemberResponse]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=50)
    space_id: str | None = None
    metadata_filters: dict[str, str | int | float | bool] = Field(default_factory=dict)


class SearchResult(BaseModel):
    document_id: str
    document_filename: str
    version: int
    position: int
    text: str
    sources: list[str]
    score: float
    metadata: dict[str, str | int | float | bool | None]


class SearchResponse(BaseModel):
    provider: str
    results: list[SearchResult]


class ReindexResponse(BaseModel):
    embedded_chunks: int
    provider: str


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    space_id: str | None = None
    metadata_filters: dict[str, str | int | float | bool] = Field(default_factory=dict)


class AnswerSourceResponse(BaseModel):
    number: int
    document_id: str
    filename: str
    version: int
    position: int
    score: float


class AskResponse(BaseModel):
    answer: str
    sources: list[AnswerSourceResponse]
    provider: str
    insufficient_evidence: bool


class SyncSummaryResponse(BaseModel):
    revisados: int
    creados: int
    actualizados: int
    sin_cambios: int
    eliminados: int
    errores: list[str]


class SyncedFileResponse(BaseModel):
    relative_path: str
    status: str
    document_id: str | None
    content_sha256: str
    last_synced_at: datetime
    last_error: str | None


class SyncStatusResponse(BaseModel):
    last_sync_at: datetime | None
    last_summary: dict
    files: list[SyncedFileResponse]


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    steps: list[str] = Field(min_length=1, max_length=10)
    space_id: str | None = None
    metadata_filters: dict[str, str | int | float | bool] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None
    steps: list[str]
    space_id: str | None
    metadata_filters: dict[str, str | int | float | bool]
    created_at: datetime
    updated_at: datetime


class AgentStepResult(BaseModel):
    question: str
    answer: str
    sources: list[AnswerSourceResponse]
    insufficient_evidence: bool


class AgentRunResponse(BaseModel):
    run_id: str
    agent_id: str
    report: str
    steps: list[AgentStepResult]
    status: str
    started_at: datetime
    finished_at: datetime


class AgentRunSummary(BaseModel):
    run_id: str
    triggered_by: str | None
    started_at: datetime
    finished_at: datetime
    status: str
    steps_count: int
    error: str | None


class AuditEventResponse(BaseModel):
    id: str
    created_at: datetime
    action: str
    actor_email: str | None
    target_type: str | None
    target_id: str | None
    summary: str | None


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, created_at=user.created_at)


def _primary_tenant_id(db: Session, user_id: str) -> str | None:
    membership = db.scalar(
        select(Membership)
        .where(Membership.user_id == user_id)
        .order_by(Membership.created_at)
    )
    return membership.tenant_id if membership else None


def _audit(
    db: Session,
    user: User,
    tenant_id: str | None,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    summary: str | None = None,
) -> None:
    """Escribe un evento en el historial de la empresa."""
    if not tenant_id:
        return
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            user_id=user.id,
            actor_email=user.email,
            action=action,
            target_type=target_type,
            target_id=target_id,
            summary=summary,
        )
    )


def _tenant_response(tenant: Tenant) -> TenantResponse:
    return TenantResponse(id=tenant.id, name=tenant.name, created_at=tenant.created_at)


def _require_space(
    db: Session, user: User, tenant_id: str, space_id: str, *, write: bool = False
) -> KnowledgeSpace:
    if write:
        require_write_access(db, user, tenant_id)
    else:
        require_read_access(db, user, tenant_id)
    space = db.scalar(
        select(KnowledgeSpace).where(
            KnowledgeSpace.id == space_id,
            KnowledgeSpace.tenant_id == tenant_id,
        )
    )
    if space is None:
        raise HTTPException(status_code=404, detail="No se encontró el espacio de conocimiento.")
    return space


def _require_optional_space(db: Session, tenant_id: str, space_id: str | None) -> None:
    """Valida el espacio opcional usado por búsqueda y preguntas."""
    if space_id is None:
        return
    space = db.scalar(
        select(KnowledgeSpace).where(
            KnowledgeSpace.id == space_id,
            KnowledgeSpace.tenant_id == tenant_id,
        )
    )
    if space is None:
        raise HTTPException(status_code=404, detail="No se encontró el espacio de conocimiento.")


def _validate_steps(steps: list[str]) -> list[str]:
    cleaned = [step.strip() for step in steps]
    if any(not step or len(step) > 1000 for step in cleaned):
        raise HTTPException(
            status_code=422, detail="Cada paso debe ser una pregunta de 1 a 1000 caracteres."
        )
    return cleaned


def _agent_response(agent: Agent) -> AgentResponse:
    return AgentResponse(
        id=agent.id,
        tenant_id=agent.tenant_id,
        name=agent.name,
        description=agent.description,
        steps=list(agent.steps_json),
        space_id=agent.space_id,
        metadata_filters=agent.metadata_filters_json or {},
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _get_document(
    db: Session, tenant_id: str, space_id: str, document_id: str, *, include_deleted: bool = False
) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
            Document.space_id == space_id,
        )
    )
    if document is None or (document.deleted_at is not None and not include_deleted):
        raise HTTPException(status_code=404, detail="No se encontró el documento.")
    return document


def _document_summary(document: Document) -> DocumentSummaryResponse:
    return DocumentSummaryResponse(
        id=document.id,
        tenant_id=document.tenant_id,
        space_id=document.space_id,
        filename=document.filename,
        file_extension=document.file_extension,
        content_sha256=document.content_sha256,
        extraction_method=document.extraction_method,
        warning_messages=document.warning_messages,
        metadata=document.metadata_json or {},
        chunk_count=len(document.current_version.chunks) if document.current_version else 0,
        version_count=len(document.versions),
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _document_response(document: Document) -> DocumentResponse:
    summary = _document_summary(document)
    current = document.current_version
    return DocumentResponse(
        **summary.model_dump(),
        version=current.version_number if current else 0,
        deleted_at=document.deleted_at,
        chunks=[
            StoredChunkResponse(position=chunk.position, text=chunk.text, sources=chunk.sources)
            for chunk in (current.chunks if current else [])
        ],
    )


def _process_upload(filename: str, content: bytes):
    try:
        return process_document(filename, content)
    except UnsupportedDocumentType as exc:
        raise DocumentError(415, str(exc)) from exc
    except OCRUnavailableError as exc:
        raise DocumentError(503, str(exc)) from exc
    except OCRProcessingError as exc:
        raise DocumentError(422, str(exc)) from exc
    except DocumentProcessingError as exc:
        raise DocumentError(422, str(exc)) from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "local-prototype"}


@app.post("/api/auth/register", response_model=RegistrationResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_session)) -> RegistrationResponse:
    email = validate_email(payload.email)
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese correo.")

    company_name = payload.company_name.strip()
    if not company_name:
        raise HTTPException(status_code=422, detail="El nombre de la empresa no puede estar vacío.")

    tenant = Tenant(name=company_name)
    user = User(email=email, password_hash=hash_password(payload.password))
    db.add_all([tenant, user])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese correo.") from exc
    db.refresh(tenant)
    db.refresh(user)

    db.add(Membership(user_id=user.id, tenant_id=tenant.id, role=ROLE_OWNER))
    _audit(
        db, user, tenant.id, "registro", target_type="empresa", target_id=tenant.id,
        summary=f"Creó la empresa {company_name}.",
    )
    token = issue_token(db, user)
    return RegistrationResponse(
        token=token,
        user=_user_response(user),
        tenant=_tenant_response(tenant),
    )


@app.post("/api/auth/login", response_model=SessionResponse)
def login(
    payload: LoginRequest, request: Request, db: Session = Depends(get_session)
) -> SessionResponse:
    email = normalize_email(payload.email)
    client_host = request.client.host if request.client else None
    check_login_attempt(email, client_host)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        record_login_failure(email, client_host)
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")
    clear_login_failures(email, client_host)
    _audit(
        db, user, _primary_tenant_id(db, user.id), "inicio_sesion", summary="Inició sesión."
    )
    token = issue_token(db, user)
    return SessionResponse(token=token, user=_user_response(user))


@app.get("/api/auth/me", response_model=MeResponse)
def read_me(
    user: User = Depends(get_current_user), db: Session = Depends(get_session)
) -> MeResponse:
    memberships = db.scalars(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at)
    ).all()
    return MeResponse(
        user=_user_response(user),
        memberships=[
            MembershipResponse(
                tenant_id=membership.tenant_id,
                tenant_name=membership.tenant.name,
                role=membership.role,
            )
            for membership in memberships
        ],
    )


@app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    authorization: str | None = Header(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> None:
    _audit(
        db, current_user, _primary_tenant_id(db, current_user.id), "cierre_sesion",
        summary="Cerró sesión.",
    )
    if authorization:
        revoke_token(db, authorization[7:].strip())
    db.commit()


@app.post("/api/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: TenantCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> TenantResponse:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="El nombre de la empresa no puede estar vacío.")
    tenant = Tenant(name=name)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    db.add(Membership(user_id=user.id, tenant_id=tenant.id, role=ROLE_OWNER))
    _audit(
        db, user, tenant.id, "crear_empresa", target_type="empresa", target_id=tenant.id,
        summary=f"Creó la empresa {name}.",
    )
    db.commit()
    return _tenant_response(tenant)


@app.get("/api/tenants/{tenant_id}/members", response_model=MemberListResponse)
def list_members(
    tenant_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> MemberListResponse:
    require_owner_access(db, user, tenant_id)
    memberships = db.scalars(
        select(Membership)
        .join(User)
        .where(Membership.tenant_id == tenant_id)
        .order_by(Membership.created_at)
    ).all()
    return MemberListResponse(
        members=[
            MemberResponse(
                user_id=membership.user_id,
                email=membership.user.email,
                role=membership.role,
                created_at=membership.created_at,
            )
            for membership in memberships
        ]
    )


@app.post(
    "/api/tenants/{tenant_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    tenant_id: str,
    payload: AddMemberRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> MemberResponse:
    require_owner_access(db, user, tenant_id)
    if payload.role not in VALID_ROLES:
        allowed = ", ".join(sorted(VALID_ROLES))
        raise HTTPException(status_code=422, detail=f"Rol no válido. Usa: {allowed}.")

    email = validate_email(payload.email)
    invited_user = db.scalar(select(User).where(User.email == email))
    if invited_user is None:
        raise HTTPException(
            status_code=404, detail="No hay ningún usuario registrado con ese correo."
        )
    if db.scalar(
        select(Membership).where(
            Membership.user_id == invited_user.id, Membership.tenant_id == tenant_id
        )
    ) is not None:
        raise HTTPException(status_code=409, detail="Ese usuario ya pertenece a la empresa.")

    membership = Membership(user_id=invited_user.id, tenant_id=tenant_id, role=payload.role)
    db.add(membership)
    _audit(
        db, user, tenant_id, "invitar_miembro", target_type="usuario",
        target_id=invited_user.id, summary=f"Invitó a {invited_user.email} como {payload.role}.",
    )
    try:
        db.commit()
        db.refresh(membership)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ese usuario ya pertenece a la empresa.") from exc
    return MemberResponse(
        user_id=membership.user_id,
        email=invited_user.email,
        role=membership.role,
        created_at=membership.created_at,
    )


@app.post(
    "/api/tenants/{tenant_id}/spaces",
    response_model=SpaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_space(
    tenant_id: str,
    payload: SpaceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> SpaceResponse:
    require_write_access(db, user, tenant_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="El nombre del espacio no puede estar vacío.")

    space = KnowledgeSpace(tenant_id=tenant_id, name=name)
    db.add(space)
    _audit(
        db, user, tenant_id, "crear_espacio", target_type="espacio", summary=f"Creó el espacio {name}."
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Ya existe un espacio con ese nombre en esta empresa."
        ) from exc
    db.refresh(space)
    return SpaceResponse(
        id=space.id, tenant_id=space.tenant_id, name=space.name, created_at=space.created_at
    )


@app.get("/api/tenants/{tenant_id}/spaces", response_model=list[SpaceResponse])
def list_spaces(
    tenant_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> list[SpaceResponse]:
    require_read_access(db, user, tenant_id)
    spaces = db.scalars(
        select(KnowledgeSpace)
        .where(KnowledgeSpace.tenant_id == tenant_id)
        .order_by(KnowledgeSpace.created_at)
    ).all()
    return [
        SpaceResponse(id=space.id, tenant_id=space.tenant_id, name=space.name, created_at=space.created_at)
        for space in spaces
    ]


def _store_document(
    db: Session, tenant_id: str, space_id: str, filename: str, content: bytes
) -> Document:
    """Guarda un archivo como versión nueva; lanza DocumentError si no se puede."""
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise DocumentError(415, f"Formato no soportado. Usa: {allowed}.")
    if len(content) > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES / 1_000_000
        raise DocumentError(413, f"El archivo supera el límite configurado de {limit_mb:g} MB.")

    result = _process_upload(filename, content)
    warnings = list(result.warnings)
    try:
        vectors = get_provider().embed([chunk.text for chunk in result.chunks])
    except EmbeddingError as exc:
        vectors = [None] * len(result.chunks)
        warnings.append(f"No se pudieron generar embeddings: {exc}")
    content_sha256 = hashlib.sha256(content).hexdigest()

    document = db.scalar(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.space_id == space_id,
            Document.filename == filename,
            Document.deleted_at.is_(None),
        )
    )
    if document is not None and document.content_sha256 == content_sha256:
        raise VersionAlreadyExists(document)

    document_id = document.id if document is not None else str(uuid.uuid4())
    version_number = 1
    if document is not None:
        version_number = max(version.version_number for version in document.versions) + 1

    storage_key = save_original(
        tenant_id=tenant_id,
        space_id=space_id,
        document_id=document_id,
        version_number=version_number,
        extension=extension,
        content=content,
    )

    is_new_document = document is None
    if is_new_document:
        document = Document(
            id=document_id,
            tenant_id=tenant_id,
            space_id=space_id,
            metadata_json={"tipo_documento": extension.lstrip(".").upper()},
        )

    version = DocumentVersion(
        tenant_id=tenant_id,
        document_id=document_id,
        version_number=version_number,
        filename=filename,
        file_extension=extension,
        content_sha256=content_sha256,
        storage_key=storage_key,
        extraction_method=result.extraction_method,
        warning_messages=list(warnings),
    )
    chunks = []
    for position, chunk in enumerate(result.chunks):
        values = {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "position": position,
            "text": chunk.text,
            "sources": list(chunk.sources),
        }
        # Si no hay vector, dejamos la columna en NULL de SQL (no en texto "null").
        if vectors[position] is not None:
            values["embedding"] = vectors[position]
        chunks.append(DocumentChunk(**values))
    version.chunks = chunks
    document.filename = filename
    document.file_extension = extension
    document.content_sha256 = content_sha256
    document.storage_key = storage_key
    document.extraction_method = result.extraction_method
    document.warning_messages = list(warnings)
    document.updated_at = utc_now()
    document.deleted_at = None

    if is_new_document:
        document.versions = [version]
        db.add(document)
    else:
        db.add(version)

    try:
        db.commit()
        db.refresh(document)
    except Exception:
        db.rollback()
        remove_original(storage_key)
        raise
    return document


@app.post(
    "/api/tenants/{tenant_id}/spaces/{space_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_document(
    tenant_id: str,
    space_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> DocumentResponse:
    _require_space(db, user, tenant_id, space_id, write=True)
    filename = Path(file.filename or "documento").name
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    try:
        document = _store_document(db, tenant_id, space_id, filename, content)
    except VersionAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    version = document.current_version.version_number if document.current_version else 0
    _audit(
        db, user, tenant_id, "subir_documento", target_type="documento", target_id=document.id,
        summary=f"Guardó {filename} como versión {version}.",
    )
    db.commit()
    return _document_response(document)


@app.get(
    "/api/tenants/{tenant_id}/spaces/{space_id}/documents",
    response_model=DocumentListResponse,
)
def list_documents(
    tenant_id: str,
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> DocumentListResponse:
    _require_space(db, user, tenant_id, space_id)
    documents = db.scalars(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.space_id == space_id,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.created_at.desc())
    ).all()
    return DocumentListResponse(documents=[_document_summary(document) for document in documents])


@app.get(
    "/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document_id}",
    response_model=DocumentResponse,
)
def get_document(
    tenant_id: str,
    space_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> DocumentResponse:
    _require_space(db, user, tenant_id, space_id)
    return _document_response(_get_document(db, tenant_id, space_id, document_id))


@app.patch(
    "/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document_id}",
    response_model=DocumentResponse,
)
def update_metadata(
    tenant_id: str,
    space_id: str,
    document_id: str,
    payload: MetadataUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> DocumentResponse:
    _require_space(db, user, tenant_id, space_id, write=True)
    document = _get_document(db, tenant_id, space_id, document_id)
    for key, value in payload.metadata.items():
        if not isinstance(value, VALID_METADATA_VALUES):
            raise HTTPException(status_code=422, detail="La metadata solo admite texto, números o banderas.")
    document.metadata_json = dict(payload.metadata)
    document.updated_at = utc_now()
    _audit(
        db, user, tenant_id, "cambiar_metadata", target_type="documento", target_id=document.id,
        summary=f"Cambió la metadata de {document.filename}.",
    )
    db.commit()
    db.refresh(document)
    return _document_response(document)


@app.delete(
    "/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document(
    tenant_id: str,
    space_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> None:
    _require_space(db, user, tenant_id, space_id, write=True)
    document = _get_document(db, tenant_id, space_id, document_id)
    document.deleted_at = utc_now()
    document.updated_at = document.deleted_at
    _audit(
        db, user, tenant_id, "ocultar_documento", target_type="documento", target_id=document.id,
        summary=f"Ocultó {document.filename}.",
    )
    db.commit()


@app.post(
    "/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document_id}/restore",
    response_model=DocumentResponse,
)
def restore_document(
    tenant_id: str,
    space_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> DocumentResponse:
    _require_space(db, user, tenant_id, space_id, write=True)
    document = _get_document(db, tenant_id, space_id, document_id, include_deleted=True)
    if document.deleted_at is None:
        raise HTTPException(status_code=409, detail="El documento ya está activo.")
    document.deleted_at = None
    document.updated_at = utc_now()
    _audit(
        db, user, tenant_id, "restaurar_documento", target_type="documento", target_id=document.id,
        summary=f"Restauró {document.filename}.",
    )
    db.commit()
    db.refresh(document)
    return _document_response(document)


@app.get(
    "/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document_id}/versions",
    response_model=VersionListResponse,
)
def list_versions(
    tenant_id: str,
    space_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> VersionListResponse:
    _require_space(db, user, tenant_id, space_id)
    document = _get_document(db, tenant_id, space_id, document_id)
    return VersionListResponse(
        versions=[
            VersionSummaryResponse(
                version_number=version.version_number,
                filename=version.filename,
                content_sha256=version.content_sha256,
                extraction_method=version.extraction_method,
                warning_messages=version.warning_messages,
                created_at=version.created_at,
            )
            for version in document.versions
        ]
    )


@app.get(
    "/api/tenants/{tenant_id}/spaces/{space_id}/documents/{document_id}/versions/{version_number}",
    response_model=VersionResponse,
)
def get_version(
    tenant_id: str,
    space_id: str,
    document_id: str,
    version_number: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> VersionResponse:
    _require_space(db, user, tenant_id, space_id)
    document = _get_document(db, tenant_id, space_id, document_id)
    version = next(
        (item for item in document.versions if item.version_number == version_number), None
    )
    if version is None:
        raise HTTPException(status_code=404, detail="No se encontró esa versión.")
    return VersionResponse(
        version_number=version.version_number,
        filename=version.filename,
        extraction_method=version.extraction_method,
        warning_messages=version.warning_messages,
        created_at=version.created_at,
        chunks=[
            StoredChunkResponse(position=chunk.position, text=chunk.text, sources=chunk.sources)
            for chunk in version.chunks
        ],
    )


@app.post("/api/tenants/{tenant_id}/search/reindex", response_model=ReindexResponse)
def reindex_embeddings(
    tenant_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> ReindexResponse:
    require_owner_access(db, user, tenant_id)
    max_version = current_version_number()
    pending = db.scalars(
        select(DocumentChunk)
        .join(
            DocumentVersion,
            and_(
                DocumentChunk.version_id == DocumentVersion.id,
                DocumentChunk.tenant_id == DocumentVersion.tenant_id,
            ),
        )
        .join(
            Document,
            and_(
                DocumentVersion.document_id == Document.id,
                DocumentVersion.tenant_id == Document.tenant_id,
            ),
        )
        .where(
            Document.tenant_id == tenant_id,
            Document.deleted_at.is_(None),
            DocumentChunk.embedding.is_(None),
            DocumentVersion.version_number == max_version,
        )
    ).all()

    try:
        provider = get_provider()
        embedded = 0
        for start in range(0, len(pending), 64):
            batch = pending[start : start + 64]
            vectors = provider.embed([chunk.text for chunk in batch])
            for chunk, vector in zip(batch, vectors):
                chunk.embedding = vector
                embedded += 1
            db.commit()
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _audit(
        db, user, tenant_id, "reindexar", summary=f"Regeneró {embedded} vectores de búsqueda."
    )
    db.commit()
    return ReindexResponse(embedded_chunks=embedded, provider=provider.name)


@app.post("/api/tenants/{tenant_id}/search", response_model=SearchResponse)
def search_documents(
    tenant_id: str,
    payload: SearchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> SearchResponse:
    require_read_access(db, user, tenant_id)
    _require_optional_space(db, tenant_id, payload.space_id)

    try:
        provider = get_provider()
        query_vector = provider.embed([payload.query])[0]
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    matches = find_similar_chunks(
        db,
        tenant_id,
        query_vector,
        payload.top_k,
        space_id=payload.space_id,
        metadata_filters=payload.metadata_filters,
    )
    return SearchResponse(
        provider=provider.name,
        results=[
            SearchResult(
                document_id=document.id,
                document_filename=document.filename,
                version=version.version_number,
                position=chunk.position,
                text=chunk.text,
                sources=chunk.sources,
                score=round(score, 4),
                metadata=document.metadata_json or {},
            )
            for chunk, version, document, score in matches
        ],
    )


def _answer_question(
    db: Session,
    tenant_id: str,
    question: str,
    *,
    top_k: int = 5,
    space_id: str | None = None,
    metadata_filters: dict[str, str | int | float | bool] | None = None,
) -> AskResponse:
    """Busca evidencia y responde. El permiso ya lo comprobó quien llama."""
    try:
        query_vector = get_provider().embed([question])[0]
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    matches = [
        match
        for match in find_similar_chunks(
            db,
            tenant_id,
            query_vector,
            top_k,
            space_id=space_id,
            metadata_filters=metadata_filters or {},
        )
        if match[3] >= MIN_ANSWER_SCORE
    ]

    sources: list[AnswerSourceResponse] = []
    chat_sources: list[ChatSource] = []
    context_lines: list[str] = []
    for number, (chunk, version, document, score) in enumerate(matches, start=1):
        rounded = round(score, 4)
        sources.append(
            AnswerSourceResponse(
                number=number,
                document_id=document.id,
                filename=version.filename,
                version=version.version_number,
                position=chunk.position,
                score=rounded,
            )
        )
        chat_sources.append(
            ChatSource(
                number=number,
                document_id=document.id,
                filename=version.filename,
                version=version.version_number,
                position=chunk.position,
                score=rounded,
            )
        )
        context_lines.append(
            f"[{number}] {chunk.text}\n"
            f"    Documento: {version.filename} (id: {document.id}), "
            f"versión {version.version_number}, posición {chunk.position}, "
            f"similitud {score:.3f}"
        )
    context = "\n\n".join(context_lines)

    if not sources:
        answer = NO_EVIDENCE_ANSWER
        provider_name = "ninguno"
    else:
        try:
            chat_provider = get_chat_provider()
            answer = chat_provider.answer(question, context, chat_sources)
        except ChatError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        provider_name = chat_provider.name

    return AskResponse(
        answer=answer,
        sources=sources,
        provider=provider_name,
        insufficient_evidence=not sources or answer.strip() == NO_EVIDENCE_ANSWER,
    )


@app.post("/api/tenants/{tenant_id}/ask", response_model=AskResponse)
def answer_question(
    tenant_id: str,
    payload: AskRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> AskResponse:
    """Responde usando solo los fragmentos recuperados y devuelve sus fuentes."""
    require_read_access(db, user, tenant_id)
    _require_optional_space(db, tenant_id, payload.space_id)
    _audit(
        db, user, tenant_id, "pregunta", summary=f"Preguntó: {payload.question[:200]}"
    )
    db.commit()
    return _answer_question(
        db,
        tenant_id,
        payload.question,
        top_k=payload.top_k,
        space_id=payload.space_id,
        metadata_filters=payload.metadata_filters,
    )


@app.post(
    "/api/tenants/{tenant_id}/agents", response_model=AgentResponse, status_code=status.HTTP_201_CREATED
)
def create_agent(
    tenant_id: str,
    payload: AgentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> AgentResponse:
    """Define una tarea con varias preguntas que se ejecutarán en orden."""
    require_write_access(db, user, tenant_id)
    _require_optional_space(db, tenant_id, payload.space_id)
    steps = _validate_steps(payload.steps)
    agent = Agent(
        tenant_id=tenant_id,
        name=payload.name.strip(),
        description=payload.description,
        steps_json=steps,
        space_id=payload.space_id,
        metadata_filters_json=payload.metadata_filters,
    )
    db.add(agent)
    _audit(
        db, user, tenant_id, "crear_agente", target_type="agente", target_id=agent.id,
        summary=f"Creó el agente {agent.name} con {len(steps)} pasos.",
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un agente con ese nombre.") from exc
    db.refresh(agent)
    return _agent_response(agent)


@app.get("/api/tenants/{tenant_id}/agents", response_model=list[AgentResponse])
def list_agents(
    tenant_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> list[AgentResponse]:
    require_read_access(db, user, tenant_id)
    agents = db.scalars(
        select(Agent).where(Agent.tenant_id == tenant_id).order_by(Agent.created_at)
    ).all()
    return [_agent_response(agent) for agent in agents]


def _get_agent(db: Session, tenant_id: str, agent_id: str) -> Agent:
    agent = db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="No se encontró el agente.")
    return agent


@app.post(
    "/api/tenants/{tenant_id}/agents/{agent_id}/run", response_model=AgentRunResponse
)
def run_agent(
    tenant_id: str,
    agent_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> AgentRunResponse:
    """Ejecuta los pasos del agente y guarda el informe con sus fuentes."""
    require_read_access(db, user, tenant_id)
    agent = _get_agent(db, tenant_id, agent_id)
    _require_optional_space(db, tenant_id, agent.space_id)

    started_at = utc_now()
    results: list[AgentStepResult] = []
    report_lines = [f"# {agent.name}", ""]
    failure: HTTPException | None = None

    for index, question in enumerate(agent.steps_json, start=1):
        try:
            answer = _answer_question(
                db,
                tenant_id,
                question,
                space_id=agent.space_id,
                metadata_filters=agent.metadata_filters_json or {},
            )
        except HTTPException as exc:
            failure = exc
            break
        results.append(
            AgentStepResult(
                question=question,
                answer=answer.answer,
                sources=answer.sources,
                insufficient_evidence=answer.insufficient_evidence,
            )
        )
        sources_text = ", ".join(
            f"{source.filename} v{source.version} [{source.number}]" for source in answer.sources
        ) or "ninguna"
        report_lines.append(f"## {index}. {question}\n\n{answer.answer}\n\nFuentes: {sources_text}")

    if failure is not None:
        status_value = "error"
        error = str(failure.detail)
        report = f"El agente no pudo completarse: {error}"
    else:
        status_value = "ok"
        error = None
        report = "\n\n".join(report_lines)

    run = AgentRun(
        tenant_id=tenant_id,
        agent_id=agent_id,
        triggered_by=user.id,
        started_at=started_at,
        finished_at=utc_now(),
        status=status_value,
        report_text=report,
        steps_json=[step.model_dump(mode="json") for step in results],
        error=error,
    )
    db.add(run)
    _audit(
        db, user, tenant_id, "ejecutar_agente", target_type="agente", target_id=agent_id,
        summary=f"Ejecutó {agent.name}: {status_value} con {len(results)} pasos.",
    )
    db.commit()
    db.refresh(run)

    if failure is not None:
        raise failure
    return AgentRunResponse(
        run_id=run.id,
        agent_id=agent_id,
        report=run.report_text,
        steps=results,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


@app.get(
    "/api/tenants/{tenant_id}/agents/{agent_id}/runs", response_model=list[AgentRunSummary]
)
def list_agent_runs(
    tenant_id: str,
    agent_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> list[AgentRunSummary]:
    """Muestra el historial de ejecuciones: cuándo, quién y con qué resultado."""
    require_read_access(db, user, tenant_id)
    _get_agent(db, tenant_id, agent_id)
    runs = db.scalars(
        select(AgentRun)
        .where(AgentRun.tenant_id == tenant_id, AgentRun.agent_id == agent_id)
        .order_by(AgentRun.started_at.desc())
        .limit(20)
    ).all()
    return [
        AgentRunSummary(
            run_id=run.id,
            triggered_by=run.triggered_by,
            started_at=run.started_at,
            finished_at=run.finished_at,
            status=run.status,
            steps_count=len(run.steps_json),
            error=run.error,
        )
        for run in runs
    ]


@app.get("/api/tenants/{tenant_id}/audit", response_model=list[AuditEventResponse])
def list_audit_events(
    tenant_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> list[AuditEventResponse]:
    """Muestra la actividad reciente de la empresa. Solo dueño o administrador."""
    require_write_access(db, user, tenant_id)
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    ).all()
    return [
        AuditEventResponse(
            id=event.id,
            created_at=event.created_at,
            action=event.action,
            actor_email=event.actor_email,
            target_type=event.target_type,
            target_id=event.target_id,
            summary=event.summary,
        )
        for event in events
    ]


@app.post(
    "/api/tenants/{tenant_id}/spaces/{space_id}/sync", response_model=SyncSummaryResponse
)
def sync_space(
    tenant_id: str,
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> SyncSummaryResponse:
    """Sincroniza los archivos de la carpeta local configurada."""
    _require_space(db, user, tenant_id, space_id, write=True)
    if not SYNC_ROOT:
        raise HTTPException(
            status_code=503,
            detail="No hay carpeta de sincronización. Configura KORVIA_SYNC_ROOT.",
        )
    try:
        files, oversized = collect_source_files(
            Path(SYNC_ROOT), MAX_UPLOAD_BYTES, SUPPORTED_EXTENSIONS
        )
    except SyncError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    started_at = utc_now()
    created = updated = unchanged = removed = 0
    errors = [f"{path}: el archivo supera el límite permitido." for path in oversized]
    seen: set[str] = set()
    records = {
        record.relative_path: record
        for record in db.scalars(
            select(SyncedFile).where(
                SyncedFile.tenant_id == tenant_id, SyncedFile.space_id == space_id
            )
        ).all()
    }

    for relative, content in files:
        seen.add(relative)
        content_hash = hashlib.sha256(content).hexdigest()
        record = records.get(relative)
        if record is not None and record.content_sha256 == content_hash and record.status == "synced":
            unchanged += 1
            continue
        try:
            document = _store_document(db, tenant_id, space_id, relative, content)
        except VersionAlreadyExists as exc:
            document = exc.document
        except DocumentError as exc:
            errors.append(f"{relative}: {exc.detail}")
            if record is not None:
                record.status = "error"
                record.last_error = exc.detail
                db.commit()
            continue

        if record is None:
            record = SyncedFile(
                tenant_id=tenant_id, space_id=space_id, relative_path=relative
            )
            db.add(record)
            created += 1
        else:
            updated += 1
        record.content_sha256 = content_hash
        record.document_id = document.id
        record.status = "synced"
        record.last_error = None
        record.last_synced_at = utc_now()
        db.commit()

    for relative, record in records.items():
        if relative in seen or record.status == "missing":
            continue
        document = db.get(Document, record.document_id) if record.document_id else None
        if (
            document is not None
            and document.tenant_id == tenant_id
            and document.space_id == space_id
            and document.deleted_at is None
        ):
            document.deleted_at = utc_now()
            document.updated_at = document.deleted_at
        record.status = "missing"
        db.commit()
        removed += 1

    summary = {
        "revisados": len(files),
        "creados": created,
        "actualizados": updated,
        "sin_cambios": unchanged,
        "eliminados": removed,
        "errores": errors,
    }
    _audit(
        db, user, tenant_id, "sincronizar", target_type="espacio", target_id=space_id,
        summary=(
            f"Revisó {len(files)} archivos: {created} creados, {updated} actualizados, "
            f"{removed} eliminados."
        ),
    )
    db.add(
        SyncRun(
            tenant_id=tenant_id,
            space_id=space_id,
            started_at=started_at,
            finished_at=utc_now(),
            summary_json=summary,
        )
    )
    db.commit()
    return SyncSummaryResponse(**summary)


@app.get("/api/tenants/{tenant_id}/spaces/{space_id}/sync", response_model=SyncStatusResponse)
def sync_status(
    tenant_id: str,
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> SyncStatusResponse:
    _require_space(db, user, tenant_id, space_id)
    run = db.scalar(
        select(SyncRun)
        .where(SyncRun.tenant_id == tenant_id, SyncRun.space_id == space_id)
        .order_by(SyncRun.started_at.desc())
    )
    records = db.scalars(
        select(SyncedFile)
        .where(SyncedFile.tenant_id == tenant_id, SyncedFile.space_id == space_id)
        .order_by(SyncedFile.relative_path)
    ).all()
    return SyncStatusResponse(
        last_sync_at=run.finished_at if run else None,
        last_summary=run.summary_json if run else {},
        files=[
            SyncedFileResponse(
                relative_path=record.relative_path,
                status=record.status,
                document_id=record.document_id,
                content_sha256=record.content_sha256,
                last_synced_at=record.last_synced_at,
                last_error=record.last_error,
            )
            for record in records
        ],
    )


@app.post("/api/documents/inspect", response_model=DocumentInspectionResponse)
async def inspect_document(
    file: UploadFile = File(...), _: User = Depends(get_current_user)
) -> DocumentInspectionResponse:
    filename = file.filename or "documento"
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(status_code=415, detail=f"Formato no soportado. Usa: {allowed}.")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES / 1_000_000
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el límite configurado de {limit_mb:g} MB.",
        )

    try:
        result = _process_upload(filename, content)
    except DocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return DocumentInspectionResponse(
        filename=filename,
        extraction_method=result.extraction_method,
        block_count=len(result.blocks),
        chunks=[
            ChunkResponse(index=index, text=chunk.text, sources=list(chunk.sources))
            for index, chunk in enumerate(result.chunks)
        ],
        warnings=list(result.warnings),
    )
