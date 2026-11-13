"""Phase 9 Security Audit: Multi-Tenant Isolation & Authorization Boundary Tests.

Verifies strict cross-tenant access controls, RLS enforcement, header spoofing prevention,
and role authorization boundaries across at least two distinct organizations.
"""

import io
import uuid
import pytest
from httpx import AsyncClient


def create_sample_pdf(text: str = "Confidential Tenant Content") -> bytes:
    """Generate in-memory valid PDF bytes."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.mark.asyncio
async def test_cross_tenant_document_and_pdf_streaming_isolation(async_client: AsyncClient):
    """Verify Tenant A cannot access Tenant B's documents or stream Tenant B's PDF files."""
    # 1. Register Tenant A
    suf_a = uuid.uuid4().hex[:8]
    res_a = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": f"Tenant A Admin {suf_a}",
            "email": f"admin_a_{suf_a}@corp.com",
            "password": "StrongPassword123!",
            "organization_name": f"Organization A {suf_a}",
        },
    )
    assert res_a.status_code == 201
    token_a = res_a.json()["access_token"]
    tenant_a_id = res_a.json()["organization"]["id"]
    headers_a = {"Authorization": f"Bearer {token_a}", "X-Tenant-ID": tenant_a_id}

    # 2. Register Tenant B
    suf_b = uuid.uuid4().hex[:8]
    res_b = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": f"Tenant B Admin {suf_b}",
            "email": f"admin_b_{suf_b}@corp.com",
            "password": "StrongPassword123!",
            "organization_name": f"Organization B {suf_b}",
        },
    )
    assert res_b.status_code == 201
    token_b = res_b.json()["access_token"]
    tenant_b_id = res_b.json()["organization"]["id"]
    headers_b = {"Authorization": f"Bearer {token_b}", "X-Tenant-ID": tenant_b_id}

    # 3. Tenant A uploads a confidential PDF
    pdf_a_bytes = create_sample_pdf("TOP SECRET TENANT A FINANCIALS")
    upload_res = await async_client.post(
        "/api/v1/documents/upload",
        files={"file": ("confidential_a.pdf", io.BytesIO(pdf_a_bytes), "application/pdf")},
        headers=headers_a,
    )
    assert upload_res.status_code == 201
    doc_a_id = upload_res.json()["id"]

    # 4. Tenant B attempts to retrieve Tenant A's document details -> HTTP 404
    get_res = await async_client.get(
        f"/api/v1/documents/{doc_a_id}",
        headers=headers_b,
    )
    assert get_res.status_code == 404, "Tenant B must not see Tenant A document metadata"

    # 5. Tenant B attempts to stream Tenant A's PDF file via GET /{document_id}/file -> HTTP 404
    stream_res = await async_client.get(
        f"/api/v1/documents/{doc_a_id}/file",
        headers=headers_b,
    )
    assert stream_res.status_code == 404, "Tenant B must not download/stream Tenant A PDF file"

    # 6. Tenant B attempts to delete Tenant A's document -> HTTP 404
    del_res = await async_client.delete(
        f"/api/v1/documents/{doc_a_id}",
        headers=headers_b,
    )
    assert del_res.status_code == 404, "Tenant B must not delete Tenant A document"

    # 7. Tenant A can successfully stream their own PDF file -> HTTP 200
    stream_a_res = await async_client.get(
        f"/api/v1/documents/{doc_a_id}/file",
        headers=headers_a,
    )
    assert stream_a_res.status_code == 200
    assert stream_a_res.headers["content-type"] == "application/pdf"
    assert len(stream_a_res.content) == len(pdf_a_bytes)


@pytest.mark.asyncio
async def test_header_spoofing_membership_validation(async_client: AsyncClient):
    """Verify modifying X-Tenant-ID header cannot bypass membership validation."""
    # Register User in Org A
    suf_a = uuid.uuid4().hex[:8]
    res_a = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": f"User A {suf_a}",
            "email": f"usera_{suf_a}@corp.com",
            "password": "StrongPassword123!",
            "organization_name": f"Org A {suf_a}",
        },
    )
    token_a = res_a.json()["access_token"]

    # Register Org B
    suf_b = uuid.uuid4().hex[:8]
    res_b = await async_client.post(
        "/api/v1/auth/register",
        json={
            "full_name": f"User B {suf_b}",
            "email": f"userb_{suf_b}@corp.com",
            "password": "StrongPassword123!",
            "organization_name": f"Org B {suf_b}",
        },
    )
    tenant_b_id = res_b.json()["organization"]["id"]

    # User A tries to use Org B's Tenant ID with User A's token -> HTTP 403 Forbidden
    spoofed_headers = {
        "Authorization": f"Bearer {token_a}",
        "X-Tenant-ID": tenant_b_id,
    }
    spoof_res = await async_client.get(
        "/api/v1/documents",
        headers=spoofed_headers,
    )
    assert spoof_res.status_code == 403
    assert "Forbidden" in spoof_res.json()["detail"]


@pytest.mark.asyncio
async def test_cross_tenant_chat_session_isolation(async_client: AsyncClient):
    """Verify Tenant A cannot view, send messages to, or access Tenant B's chat sessions."""
    # Register Tenant A & B
    suf_a = uuid.uuid4().hex[:8]
    res_a = await async_client.post(
        "/api/v1/auth/register",
        json={"full_name": f"Chat A {suf_a}", "email": f"chata_{suf_a}@corp.com", "password": "Password123!", "organization_name": f"Chat Org A {suf_a}"},
    )
    headers_a = {"Authorization": f"Bearer {res_a.json()['access_token']}", "X-Tenant-ID": res_a.json()["organization"]["id"]}

    suf_b = uuid.uuid4().hex[:8]
    res_b = await async_client.post(
        "/api/v1/auth/register",
        json={"full_name": f"Chat B {suf_b}", "email": f"chatb_{suf_b}@corp.com", "password": "Password123!", "organization_name": f"Chat Org B {suf_b}"},
    )
    headers_b = {"Authorization": f"Bearer {res_b.json()['access_token']}", "X-Tenant-ID": res_b.json()["organization"]["id"]}

    # Tenant A creates a chat session
    session_res = await async_client.post(
        "/api/v1/chat/sessions",
        json={"title": "Confidential Strategy Session"},
        headers=headers_a,
    )
    assert session_res.status_code == 201
    session_a_id = session_res.json()["id"]

    # Tenant B tries to retrieve Tenant A's chat session -> HTTP 404
    get_res = await async_client.get(
        f"/api/v1/chat/sessions/{session_a_id}",
        headers=headers_b,
    )
    assert get_res.status_code == 404

    # Tenant B tries to delete Tenant A's chat session -> HTTP 404
    del_res = await async_client.delete(
        f"/api/v1/chat/sessions/{session_a_id}",
        headers=headers_b,
    )
    assert del_res.status_code == 404


@pytest.mark.asyncio
async def test_role_based_access_control_boundaries(async_client: AsyncClient):
    """Verify users with MEMBER role cannot perform OWNER/ADMIN actions."""
    # 1. Register Owner
    suf = uuid.uuid4().hex[:8]
    owner_res = await async_client.post(
        "/api/v1/auth/register",
        json={"full_name": f"Owner {suf}", "email": f"owner_{suf}@corp.com", "password": "Password123!", "organization_name": f"RBAC Org {suf}"},
    )
    owner_headers = {"Authorization": f"Bearer {owner_res.json()['access_token']}", "X-Tenant-ID": owner_res.json()["organization"]["id"]}
    tenant_id = owner_res.json()["organization"]["id"]

    # 2. Register a second user to become a normal MEMBER
    member_suf = uuid.uuid4().hex[:8]
    member_reg = await async_client.post(
        "/api/v1/auth/register",
        json={"full_name": f"Member {member_suf}", "email": f"member_{member_suf}@corp.com", "password": "Password123!", "organization_name": f"Solo Org {member_suf}"},
    )
    member_token = member_reg.json()["access_token"]
    member_user_id = member_reg.json()["user"]["id"]

    # 3. Owner invites Member to Org with MEMBER role
    invite_res = await async_client.post(
        f"/api/v1/tenants/{tenant_id}/members",
        json={"email": f"member_{member_suf}@corp.com", "role": "MEMBER"},
        headers=owner_headers,
    )
    assert invite_res.status_code in [200, 201]

    # 4. Member switches headers to the shared Org
    member_headers = {"Authorization": f"Bearer {member_token}", "X-Tenant-ID": tenant_id}

    # 5. Member attempts to update Organization details (Owner-only) -> HTTP 403 Forbidden
    patch_res = await async_client.patch(
        f"/api/v1/tenants/{tenant_id}",
        json={"name": "Hacked Org Name"},
        headers=member_headers,
    )
    assert patch_res.status_code == 403
