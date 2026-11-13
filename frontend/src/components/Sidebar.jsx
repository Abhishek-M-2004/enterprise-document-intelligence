import React, { useEffect, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  FileText,
  Search,
  Settings,
  MessageSquare,
  BarChart3,
  Layers,
  Shield,
  Building2,
  LogOut,
  ChevronRight,
  ExternalLink,
  X,
  Activity,
} from 'lucide-react';
import { getSystemHealth } from '../services/api';
import { useAuth } from '../context/AuthContext';
import Badge from './ui/Badge';

export default function Sidebar({ isOpen, onClose }) {
  const { user, currentTenant, tenants, switchTenant, logout } = useAuth();
  const [healthStatus, setHealthStatus] = useState({ status: 'checking', message: 'Checking API...' });
  const [orgDropdownOpen, setOrgDropdownOpen] = useState(false);
  const location = useLocation();

  // Close mobile sidebar on route change
  useEffect(() => {
    if (onClose) onClose();
  }, [location.pathname]);

  // Periodic health ping
  useEffect(() => {
    let isMounted = true;
    const fetchHealth = async () => {
      try {
        const data = await getSystemHealth();
        if (isMounted) {
          setHealthStatus({
            status: data.status,
            latency: data.components?.database?.latency_ms,
            message: data.status === 'healthy' ? 'Platform Online' : `API ${data.status}`,
          });
        }
      } catch (err) {
        if (isMounted) {
          setHealthStatus({ status: 'offline', message: 'API Offline' });
        }
      }
    };

    fetchHealth();
    const interval = setInterval(fetchHealth, 20000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const navItems = [
    { name: 'Dashboard', path: '/', icon: LayoutDashboard },
    { name: 'Documents', path: '/documents', icon: FileText },
    { name: 'AI Assistant', path: '/chat', icon: MessageSquare },
    { name: 'Search Workbench', path: '/query', icon: Search },
    { name: 'RAG Evaluation', path: '/evaluation', icon: BarChart3 },
    { name: 'Settings & Members', path: '/settings', icon: Settings },
  ];

  const sidebarContent = (
    <div className="flex flex-col h-full bg-slate-900 text-slate-300 border-r border-slate-800">
      {/* 1. Brand Logo & Title */}
      <div className="h-16 flex items-center justify-between px-5 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white font-bold text-sm shadow-md shadow-indigo-600/30">
            <Layers className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-white tracking-tight flex items-center gap-1.5">
              DocIntelligence
            </h1>
            <span className="text-[10px] text-slate-400 font-mono tracking-wider uppercase">
              Enterprise SaaS
            </span>
          </div>
        </div>

        {/* Mobile close button */}
        {onClose && (
          <button
            onClick={onClose}
            className="lg:hidden p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        )}
      </div>

      {/* 2. Tenant Selector Pill */}
      <div className="p-3 border-b border-slate-800/80">
        <div className="relative">
          <button
            onClick={() => setOrgDropdownOpen(!orgDropdownOpen)}
            className="w-full text-left p-2.5 bg-slate-800/90 hover:bg-slate-800 rounded-xl border border-slate-700/60 transition group"
          >
            <div className="flex items-center justify-between text-[11px] mb-1">
              <span className="text-slate-400 flex items-center gap-1 font-medium">
                <Building2 className="w-3 h-3 text-indigo-400" />
                Active Organization
              </span>
              <span className="inline-flex items-center gap-1 text-[10px] text-emerald-400 font-medium">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                Isolated
              </span>
            </div>

            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-semibold text-slate-100 truncate group-hover:text-white">
                {currentTenant?.tenant_name || 'Select Organization'}
              </span>
              <span className="text-[10px] px-1.5 py-0.2 bg-slate-700 text-indigo-300 rounded font-mono font-bold uppercase shrink-0">
                {currentTenant?.role || 'MEMBER'}
              </span>
            </div>
          </button>

          {/* Org switcher dropdown */}
          {orgDropdownOpen && (
            <div className="absolute left-0 right-0 mt-1.5 bg-slate-800 border border-slate-700 rounded-xl shadow-2xl py-1.5 z-50">
              <div className="px-3 py-1 text-[10px] font-bold text-slate-400 uppercase tracking-wider border-b border-slate-700/60">
                Switch Organization
              </div>
              <div className="max-h-48 overflow-y-auto">
                {tenants.map((t) => {
                  const isSelected = t.tenant_id === currentTenant?.tenant_id;
                  return (
                    <button
                      key={t.tenant_id}
                      onClick={() => {
                        switchTenant(t.tenant_id);
                        setOrgDropdownOpen(false);
                      }}
                      className={`w-full text-left px-3 py-2 text-xs flex items-center justify-between hover:bg-slate-700/60 transition ${
                        isSelected ? 'bg-indigo-600/20 text-indigo-300 font-semibold' : 'text-slate-300'
                      }`}
                    >
                      <span className="truncate">{t.tenant_name}</span>
                      <span className="text-[10px] text-slate-400 font-mono uppercase">{t.role}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 3. Navigation Links */}
      <nav className="flex-1 px-3 py-3 space-y-1 overflow-y-auto">
        <div className="px-3 py-1.5 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
          Workspace
        </div>

        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.name}
              to={item.path}
              className={({ isActive }) =>
                `flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition-all group ${
                  isActive
                    ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-600/30'
                    : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                }`
              }
            >
              <div className="flex items-center gap-2.5">
                <Icon className="w-4 h-4 shrink-0 transition-colors" />
                <span>{item.name}</span>
              </div>
              <ChevronRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-100 transition-opacity text-slate-400" />
            </NavLink>
          );
        })}
      </nav>

      {/* 4. Platform Status & System Health */}
      <div className="px-3 py-2.5 border-t border-slate-800 text-xs">
        <div className="flex items-center justify-between p-2 rounded-lg bg-slate-800/60 border border-slate-800">
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                healthStatus.status === 'healthy' ? 'bg-emerald-400' : 'bg-amber-400'
              }`}
            />
            <span className="text-[11px] font-medium text-slate-300">{healthStatus.message}</span>
          </div>
          {healthStatus.latency && (
            <span className="text-[10px] font-mono text-slate-400">{healthStatus.latency}ms</span>
          )}
        </div>
      </div>

      {/* 5. User Account Footer */}
      <div className="p-3 border-t border-slate-800 shrink-0">
        <div className="flex items-center justify-between gap-2 p-2 rounded-xl bg-slate-800/40">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-7 h-7 rounded-full bg-indigo-600 text-white flex items-center justify-center font-bold text-xs shrink-0 shadow-sm">
              {user?.full_name ? user.full_name[0].toUpperCase() : 'U'}
            </div>
            <div className="truncate text-xs">
              <p className="font-semibold text-slate-200 truncate">{user?.full_name || 'User'}</p>
              <p className="text-[10px] text-slate-400 font-mono truncate">{user?.email}</p>
            </div>
          </div>
          <button
            onClick={logout}
            className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-slate-800 rounded-lg transition"
            title="Sign out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Fixed Sidebar */}
      <aside className="hidden lg:flex w-64 flex-col shrink-0 h-screen sticky top-0 z-30">
        {sidebarContent}
      </aside>

      {/* Mobile Drawer Backdrop & Sidebar */}
      {isOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div
            className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity"
            onClick={onClose}
          />
          <aside className="relative w-72 max-w-[85vw] flex flex-col z-50 h-full shadow-2xl">
            {sidebarContent}
          </aside>
        </div>
      )}
    </>
  );
}
