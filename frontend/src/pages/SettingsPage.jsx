import React, { useState, useEffect, useCallback } from 'react';
import {
  Building2,
  Users,
  Shield,
  Key,
  Database,
  CheckCircle2,
  AlertCircle,
  Copy,
  Check,
  UserPlus,
  Trash2,
  Edit2,
  RefreshCw,
  Cpu,
  Layers,
  Sparkles,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { tenantApi } from '../services/api';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Card, { CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';
import Modal from '../components/ui/Modal';

export default function SettingsPage() {
  const { user, currentTenant, loadUserProfile } = useAuth();
  const [activeTab, setActiveTab] = useState('organization'); // 'organization' | 'members' | 'profile' | 'infrastructure'

  // Organization settings state
  const [orgName, setOrgName] = useState(currentTenant?.tenant_name || '');
  const [orgSlug, setOrgSlug] = useState(currentTenant?.tenant_slug || '');
  const [isSavingOrg, setIsSavingOrg] = useState(false);
  const [orgSuccess, setOrgSuccess] = useState(null);
  const [orgError, setOrgError] = useState(null);

  // Members state
  const [members, setMembers] = useState([]);
  const [isLoadingMembers, setIsLoadingMembers] = useState(false);
  const [memberError, setMemberError] = useState(null);
  const [memberSuccess, setMemberSuccess] = useState(null);

  // Add Member Modal
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newMemberEmail, setNewMemberEmail] = useState('');
  const [newMemberRole, setNewMemberRole] = useState('MEMBER');
  const [isAddingMember, setIsAddingMember] = useState(false);

  // Delete Member Confirmation Modal
  const [deleteMemberTarget, setDeleteMemberTarget] = useState(null);
  const [isDeletingMember, setIsDeletingMember] = useState(false);

  // Copied helper
  const [copiedKey, setCopiedKey] = useState(null);

  const tenantId = currentTenant?.tenant_id || currentTenant?.id;
  const isOwner = currentTenant?.role === 'OWNER';
  const isAdmin = currentTenant?.role === 'ADMIN' || isOwner;

  useEffect(() => {
    if (currentTenant) {
      setOrgName(currentTenant.tenant_name || '');
      setOrgSlug(currentTenant.tenant_slug || '');
    }
  }, [currentTenant]);

  // Load members if permitted
  const loadMembers = useCallback(async () => {
    if (!tenantId || !isAdmin) return;
    setIsLoadingMembers(true);
    setMemberError(null);
    try {
      const res = await tenantApi.listMembers(tenantId);
      setMembers(res.data || []);
    } catch (err) {
      setMemberError(err.response?.data?.detail || 'Failed to retrieve member roster.');
    } finally {
      setIsLoadingMembers(false);
    }
  }, [tenantId, isAdmin]);

  useEffect(() => {
    if (activeTab === 'members') {
      loadMembers();
    }
  }, [activeTab, loadMembers]);

  // Save Organization Details (Owner only)
  const handleSaveOrganization = async (e) => {
    e.preventDefault();
    if (!tenantId || !isOwner) return;

    setIsSavingOrg(true);
    setOrgSuccess(null);
    setOrgError(null);
    try {
      await tenantApi.update(tenantId, {
        name: orgName.trim(),
        slug: orgSlug.trim(),
      });
      setOrgSuccess('Organization configuration updated successfully.');
      if (loadUserProfile) await loadUserProfile();
      setTimeout(() => setOrgSuccess(null), 4000);
    } catch (err) {
      setOrgError(err.response?.data?.detail || 'Failed to update organization profile.');
    } finally {
      setIsSavingOrg(false);
    }
  };

  // Add Member
  const handleAddMember = async (e) => {
    e.preventDefault();
    if (!newMemberEmail.trim() || !tenantId) return;

    setIsAddingMember(true);
    setMemberError(null);
    try {
      await tenantApi.addMember(tenantId, {
        email: newMemberEmail.trim(),
        role: newMemberRole,
      });
      setMemberSuccess(`Added ${newMemberEmail.trim()} as ${newMemberRole}.`);
      setNewMemberEmail('');
      setIsAddModalOpen(false);
      await loadMembers();
      setTimeout(() => setMemberSuccess(null), 4000);
    } catch (err) {
      setMemberError(err.response?.data?.detail || 'Failed to add organization member.');
    } finally {
      setIsAddingMember(false);
    }
  };

  // Update Member Role
  const handleRoleChange = async (targetUserId, newRole) => {
    if (!tenantId || !isOwner) return;
    try {
      await tenantApi.updateMemberRole(tenantId, targetUserId, { role: newRole });
      setMemberSuccess('Member permission updated.');
      await loadMembers();
      setTimeout(() => setMemberSuccess(null), 3000);
    } catch (err) {
      setMemberError(err.response?.data?.detail || 'Failed to update member role.');
    }
  };

  // Delete Member
  const handleConfirmDeleteMember = async () => {
    if (!deleteMemberTarget || !tenantId) return;
    setIsDeletingMember(true);
    try {
      await tenantApi.removeMember(tenantId, deleteMemberTarget.user_id);
      setMemberSuccess(`Removed ${deleteMemberTarget.user_email || 'member'} from organization.`);
      setDeleteMemberTarget(null);
      await loadMembers();
      setTimeout(() => setMemberSuccess(null), 4000);
    } catch (err) {
      setMemberError(err.response?.data?.detail || 'Failed to remove member.');
    } finally {
      setIsDeletingMember(false);
    }
  };

  const copyToClipboard = (text, key) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  return (
    <div className="space-y-6 max-w-6xl mx-auto pb-12">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-5 border-b border-slate-200">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Organization & Settings</h1>
          <p className="text-sm text-slate-500 mt-1">
            Manage your workspace profile, team members, tenant policies, and isolated infrastructure.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={isOwner ? 'purple' : isAdmin ? 'indigo' : 'neutral'} size="md">
            Your Role: {currentTenant?.role || 'MEMBER'}
          </Badge>
        </div>
      </div>

      {/* Settings Navigation Tabs */}
      <div className="flex border-b border-slate-200 gap-1 sm:gap-4 overflow-x-auto">
        <button
          onClick={() => setActiveTab('organization')}
          className={`flex items-center gap-2 pb-3 px-2 border-b-2 text-sm font-medium transition ${
            activeTab === 'organization'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Building2 className="w-4 h-4" />
          <span>Organization Profile</span>
        </button>

        <button
          onClick={() => setActiveTab('members')}
          className={`flex items-center gap-2 pb-3 px-2 border-b-2 text-sm font-medium transition ${
            activeTab === 'members'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Users className="w-4 h-4" />
          <span>Members & RBAC</span>
          {members.length > 0 && (
            <span className="text-[11px] px-1.5 py-0.2 bg-slate-100 text-slate-600 rounded-full font-mono">
              {members.length}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab('profile')}
          className={`flex items-center gap-2 pb-3 px-2 border-b-2 text-sm font-medium transition ${
            activeTab === 'profile'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Shield className="w-4 h-4" />
          <span>User Account</span>
        </button>

        <button
          onClick={() => setActiveTab('infrastructure')}
          className={`flex items-center gap-2 pb-3 px-2 border-b-2 text-sm font-medium transition ${
            activeTab === 'infrastructure'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Database className="w-4 h-4" />
          <span>Tenant Infrastructure</span>
        </button>
      </div>

      {/* Global Alerts */}
      {orgSuccess && (
        <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl flex items-center gap-2.5 text-xs text-emerald-800">
          <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
          <span>{orgSuccess}</span>
        </div>
      )}
      {orgError && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl flex items-center gap-2.5 text-xs text-rose-800">
          <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
          <span>{orgError}</span>
        </div>
      )}
      {memberSuccess && (
        <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl flex items-center gap-2.5 text-xs text-emerald-800">
          <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
          <span>{memberSuccess}</span>
        </div>
      )}
      {memberError && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl flex items-center gap-2.5 text-xs text-rose-800">
          <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
          <span>{memberError}</span>
        </div>
      )}

      {/* TAB 1: ORGANIZATION PROFILE */}
      {activeTab === 'organization' && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Organization Information</CardTitle>
                <CardDescription>
                  Identity and URL identifier for your enterprise workspace.
                </CardDescription>
              </div>
              <Badge variant="indigo" size="sm">
                Tenant Isolation Active
              </Badge>
            </CardHeader>

            <CardContent>
              <form onSubmit={handleSaveOrganization} className="space-y-4 max-w-xl">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase mb-1.5">
                    Organization Name
                  </label>
                  <input
                    type="text"
                    required
                    disabled={!isOwner}
                    value={orgName}
                    onChange={(e) => setOrgName(e.target.value)}
                    className="w-full text-sm border-slate-300 rounded-lg px-3 py-2 border focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 disabled:bg-slate-50 disabled:text-slate-500 transition"
                  />
                  {!isOwner && (
                    <p className="text-[11px] text-slate-400 mt-1">
                      Only organization Owners can rename the organization.
                    </p>
                  )}
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase mb-1.5">
                    Organization Slug (URL Identifier)
                  </label>
                  <div className="flex items-center">
                    <span className="inline-flex items-center px-3 py-2 rounded-l-lg border border-r-0 border-slate-300 bg-slate-50 text-slate-500 text-xs font-mono">
                      app/
                    </span>
                    <input
                      type="text"
                      required
                      disabled={!isOwner}
                      value={orgSlug}
                      onChange={(e) => setOrgSlug(e.target.value)}
                      className="w-full text-sm border-slate-300 rounded-r-lg px-3 py-2 border focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 disabled:bg-slate-50 disabled:text-slate-500 font-mono transition"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase mb-1.5">
                    Tenant UUID (System Identifier)
                  </label>
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      readOnly
                      value={tenantId || ''}
                      className="w-full text-xs font-mono bg-slate-50 border border-slate-200 text-slate-600 rounded-lg px-3 py-2 select-all"
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => copyToClipboard(tenantId, 'tenantId')}
                      icon={copiedKey === 'tenantId' ? Check : Copy}
                    >
                      {copiedKey === 'tenantId' ? 'Copied' : 'Copy'}
                    </Button>
                  </div>
                  <p className="text-[11px] text-slate-400 mt-1">
                    Used automatically in HTTP headers (<code className="font-mono">X-Tenant-ID</code>) for PostgreSQL Row-Level Security partition enforcement.
                  </p>
                </div>

                {isOwner && (
                  <div className="pt-2">
                    <Button
                      type="submit"
                      variant="primary"
                      size="md"
                      isLoading={isSavingOrg}
                    >
                      Save Organization Changes
                    </Button>
                  </div>
                )}
              </form>
            </CardContent>
          </Card>
        </div>
      )}

      {/* TAB 2: MEMBERS & RBAC */}
      {activeTab === 'members' && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Member Directory & Role Assignments</CardTitle>
                <CardDescription>
                  Control access to organization documents, search indexes, and evaluation benchmarks.
                </CardDescription>
              </div>

              {isAdmin && (
                <Button
                  variant="primary"
                  size="sm"
                  icon={UserPlus}
                  onClick={() => setIsAddModalOpen(true)}
                >
                  Invite Member
                </Button>
              )}
            </CardHeader>

            <CardContent className="p-0">
              {isLoadingMembers ? (
                <div className="p-8 text-center text-slate-400 text-sm flex items-center justify-center gap-2">
                  <RefreshCw className="w-4 h-4 animate-spin text-indigo-600" />
                  <span>Loading members...</span>
                </div>
              ) : members.length === 0 ? (
                <div className="p-8 text-center text-slate-400 text-sm">
                  No other members found in this tenant directory.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm border-collapse">
                    <thead>
                      <tr className="border-b border-slate-200 bg-slate-50/70 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                        <th className="py-3 px-4">Member</th>
                        <th className="py-3 px-4">Email</th>
                        <th className="py-3 px-4">Role</th>
                        <th className="py-3 px-4">Joined</th>
                        {isOwner && <th className="py-3 px-4 text-right">Actions</th>}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {members.map((m) => {
                        const isSelf = m.user_id === user?.id;
                        return (
                          <tr key={m.id} className="hover:bg-slate-50/80 transition-colors">
                            <td className="py-3.5 px-4 font-semibold text-slate-900">
                              <div className="flex items-center gap-2.5">
                                <div className="w-7 h-7 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-bold">
                                  {m.user_email ? m.user_email[0].toUpperCase() : 'U'}
                                </div>
                                <span>{m.user_name || m.user_email?.split('@')[0]}</span>
                                {isSelf && (
                                  <span className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded font-medium">
                                    You
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="py-3.5 px-4 text-slate-600 font-mono text-xs">
                              {m.user_email}
                            </td>
                            <td className="py-3.5 px-4">
                              {isOwner && !isSelf ? (
                                <select
                                  value={m.role}
                                  onChange={(e) => handleRoleChange(m.user_id, e.target.value)}
                                  className="text-xs font-medium border-slate-300 rounded px-2 py-1 bg-white focus:ring-indigo-500 focus:border-indigo-500"
                                >
                                  <option value="MEMBER">MEMBER (Read/Query)</option>
                                  <option value="ADMIN">ADMIN (Upload/Delete/Manage)</option>
                                  <option value="OWNER">OWNER (Full Control)</option>
                                </select>
                              ) : (
                                <Badge
                                  variant={
                                    m.role === 'OWNER'
                                      ? 'purple'
                                      : m.role === 'ADMIN'
                                      ? 'indigo'
                                      : 'neutral'
                                  }
                                  size="sm"
                                >
                                  {m.role}
                                </Badge>
                              )}
                            </td>
                            <td className="py-3.5 px-4 text-xs text-slate-500">
                              {m.created_at ? new Date(m.created_at).toLocaleDateString() : 'Active'}
                            </td>
                            {isOwner && (
                              <td className="py-3.5 px-4 text-right">
                                {!isSelf && (
                                  <button
                                    onClick={() => setDeleteMemberTarget(m)}
                                    className="p-1 text-slate-400 hover:text-rose-600 rounded hover:bg-rose-50 transition"
                                    title="Remove from organization"
                                  >
                                    <Trash2 className="w-4 h-4" />
                                  </button>
                                )}
                              </td>
                            )}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* TAB 3: USER ACCOUNT */}
      {activeTab === 'profile' && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>User Profile</CardTitle>
                <CardDescription>
                  Your authenticated platform credentials and active session token properties.
                </CardDescription>
              </div>
              <Badge variant="emerald" dot size="sm">
                Verified Account
              </Badge>
            </CardHeader>

            <CardContent className="space-y-4 max-w-xl">
              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
                  Full Name
                </label>
                <div className="text-sm font-semibold text-slate-800 p-2.5 bg-slate-50 rounded-lg border border-slate-200">
                  {user?.full_name || 'N/A'}
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
                  Email Address
                </label>
                <div className="text-sm font-mono text-slate-800 p-2.5 bg-slate-50 rounded-lg border border-slate-200">
                  {user?.email || 'N/A'}
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
                  User ID (UUID)
                </label>
                <div className="text-xs font-mono text-slate-600 p-2.5 bg-slate-50 rounded-lg border border-slate-200 flex items-center justify-between">
                  <span>{user?.id}</span>
                  <button
                    onClick={() => copyToClipboard(user?.id, 'userId')}
                    className="text-indigo-600 hover:text-indigo-800 font-sans text-xs font-medium"
                  >
                    {copiedKey === 'userId' ? 'Copied' : 'Copy'}
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
                  Authentication Security
                </label>
                <div className="p-3 bg-indigo-50/50 border border-indigo-100 rounded-lg text-xs text-indigo-900 leading-relaxed">
                  Tokens are signed via HMAC-SHA256 with 15-minute rotation. Secure HttpOnly cookies provide transparent single-flight token refreshing.
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* TAB 4: TENANT INFRASTRUCTURE */}
      {activeTab === 'infrastructure' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Qdrant Vector Partition</CardTitle>
                <CardDescription>Dense vector embeddings space</CardDescription>
              </div>
              <Badge variant="cyan" size="sm">Collection Active</Badge>
            </CardHeader>
            <CardContent className="space-y-3 text-xs">
              <div className="flex justify-between py-1.5 border-b border-slate-100">
                <span className="text-slate-500">Collection Name:</span>
                <span className="font-mono font-semibold text-slate-800">enterprise_document_chunks</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-slate-100">
                <span className="text-slate-500">Embedding Model:</span>
                <span className="font-mono text-slate-800">BAAI/bge-small-en-v1.5</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-slate-100">
                <span className="text-slate-500">Vector Dimensions:</span>
                <span className="font-mono font-semibold text-slate-800">384 dimensions (Cosine)</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-slate-100">
                <span className="text-slate-500">Tenant Filter:</span>
                <span className="font-mono text-emerald-600 font-semibold">Strict Payload Isolation</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Rate Limit Quotas</CardTitle>
                <CardDescription>Redis sliding-window policies</CardDescription>
              </div>
              <Badge variant="emerald" size="sm">Active Guardrails</Badge>
            </CardHeader>
            <CardContent className="space-y-3 text-xs">
              <div className="flex justify-between py-1.5 border-b border-slate-100">
                <span className="text-slate-500">Authentication Quota:</span>
                <span className="font-mono font-semibold text-slate-800">20 req / min</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-slate-100">
                <span className="text-slate-500">Document Uploads:</span>
                <span className="font-mono font-semibold text-slate-800">25 req / min</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-slate-100">
                <span className="text-slate-500">Hybrid Search:</span>
                <span className="font-mono font-semibold text-slate-800">120 req / min</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-slate-100">
                <span className="text-slate-500">Conversational AI Chat:</span>
                <span className="font-mono font-semibold text-slate-800">60 req / min</span>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* MODAL: ADD MEMBER */}
      <Modal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        title="Add Organization Member"
        description={`Invite a platform user to join ${currentTenant?.tenant_name}`}
      >
        <form onSubmit={handleAddMember} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-700 uppercase mb-1.5">
              Member Email Address
            </label>
            <input
              type="email"
              required
              placeholder="colleague@example.com"
              value={newMemberEmail}
              onChange={(e) => setNewMemberEmail(e.target.value)}
              className="w-full text-sm border-slate-300 rounded-lg px-3 py-2 border focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 uppercase mb-1.5">
              Assigned Role
            </label>
            <select
              value={newMemberRole}
              onChange={(e) => setNewMemberRole(e.target.value)}
              className="w-full text-sm border-slate-300 rounded-lg px-3 py-2 border focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 bg-white"
            >
              <option value="MEMBER">MEMBER (Read, Search, Conversational Chat)</option>
              <option value="ADMIN">ADMIN (Upload, Manage Documents, Invite Members)</option>
              {isOwner && <option value="OWNER">OWNER (Full Tenant Administration)</option>}
            </select>
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsAddModalOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              isLoading={isAddingMember}
            >
              Add to Organization
            </Button>
          </div>
        </form>
      </Modal>

      {/* MODAL: DELETE MEMBER CONFIRMATION */}
      <Modal
        isOpen={!!deleteMemberTarget}
        onClose={() => setDeleteMemberTarget(null)}
        title="Remove Member"
        description="Are you sure you want to remove this member from the organization?"
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            <span className="font-semibold text-slate-900">{deleteMemberTarget?.user_email}</span> will immediately lose access to this organization's documents, search indexes, and conversational history.
          </p>

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDeleteMemberTarget(null)}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              isLoading={isDeletingMember}
              onClick={handleConfirmDeleteMember}
            >
              Remove Member
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
