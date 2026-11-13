import React, { useState, useRef, useEffect } from 'react';
import { useLocation, Link, useNavigate } from 'react-router-dom';
import {
  Menu,
  Building2,
  User,
  LogOut,
  ChevronDown,
  ExternalLink,
  MessageSquare,
  UploadCloud,
  Settings,
  Sparkles,
  Layers,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Badge from './ui/Badge';
import Button from './ui/Button';

export default function Navbar({ onToggleSidebar }) {
  const { user, currentTenant, logout } = useAuth();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const menuRef = useRef(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Compute breadcrumbs
  const getPageTitle = (pathname) => {
    if (pathname === '/') return 'Dashboard';
    if (pathname.startsWith('/documents')) return 'Documents & Ingestion';
    if (pathname.startsWith('/chat')) return 'AI Assistant';
    if (pathname.startsWith('/query')) return 'Search Workbench';
    if (pathname.startsWith('/evaluation')) return 'RAG Evaluation';
    if (pathname.startsWith('/settings')) return 'Organization & Settings';
    return 'Workspace';
  };

  const pageTitle = getPageTitle(location.pathname);

  return (
    <header className="h-16 bg-white border-b border-slate-200/80 flex items-center justify-between px-4 sm:px-6 shrink-0 shadow-[0_1px_2px_0_rgba(15,23,42,0.02)] relative z-20">
      {/* Left: Mobile Menu Toggle & Breadcrumbs */}
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleSidebar}
          className="lg:hidden p-2 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition focus:outline-none focus:ring-2 focus:ring-slate-300"
          aria-label="Toggle Navigation Menu"
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Clean Breadcrumb Hierarchy */}
        <div className="flex items-center gap-2 text-xs">
          <span className="font-semibold text-slate-400 hidden sm:inline">Workspace</span>
          <span className="text-slate-300 hidden sm:inline">/</span>
          <span className="font-medium text-slate-600 hidden md:inline truncate max-w-[140px]">
            {currentTenant?.tenant_name || 'Organization'}
          </span>
          <span className="text-slate-300 hidden md:inline">/</span>
          <span className="font-bold text-slate-900 tracking-tight">{pageTitle}</span>
        </div>
      </div>

      {/* Right: Quick Actions & Profile Dropdown */}
      <div className="flex items-center gap-2.5 sm:gap-3">
        {/* Quick Action: New Chat */}
        {location.pathname !== '/chat' && (
          <Link
            to="/chat"
            className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-slate-50 hover:bg-slate-100 border border-slate-200/90 rounded-lg shadow-sm transition"
          >
            <MessageSquare className="w-3.5 h-3.5 text-indigo-600" />
            <span>New Chat</span>
          </Link>
        )}

        {/* Quick Action: Upload */}
        {location.pathname !== '/documents' && (
          <Link
            to="/documents"
            className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-slate-50 hover:bg-slate-100 border border-slate-200/90 rounded-lg shadow-sm transition"
          >
            <UploadCloud className="w-3.5 h-3.5 text-indigo-600" />
            <span>Upload PDF</span>
          </Link>
        )}

        {/* User Profile Menu */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setUserMenuOpen(!userMenuOpen)}
            className="flex items-center gap-2 p-1 sm:pl-2 sm:pr-2.5 rounded-full sm:rounded-lg hover:bg-slate-50 border border-transparent hover:border-slate-200 transition select-none"
          >
            <div className="w-7 h-7 rounded-full bg-indigo-600 text-white flex items-center justify-center font-bold text-xs shadow-sm shadow-indigo-600/30">
              {user?.full_name ? user.full_name[0].toUpperCase() : 'U'}
            </div>
            <div className="hidden sm:block text-left text-xs">
              <span className="font-semibold text-slate-800 block leading-tight truncate max-w-[100px]">
                {user?.full_name?.split(' ')[0] || 'User'}
              </span>
              <span className="text-[10px] text-slate-400 font-mono block">
                {currentTenant?.role || 'MEMBER'}
              </span>
            </div>
            <ChevronDown className="w-3 h-3 text-slate-400 hidden sm:block" />
          </button>

          {/* Dropdown Menu */}
          {userMenuOpen && (
            <div className="absolute right-0 mt-2 w-64 bg-white border border-slate-200/90 rounded-xl shadow-xl py-1 z-50 animate-in fade-in slide-in-from-top-1 duration-150">
              {/* User info banner */}
              <div className="px-4 py-3 border-b border-slate-100">
                <p className="text-xs font-bold text-slate-900 truncate">{user?.full_name}</p>
                <p className="text-[11px] text-slate-500 font-mono truncate mt-0.5">{user?.email}</p>
                <div className="mt-2 flex items-center justify-between">
                  <span className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">
                    Role
                  </span>
                  <Badge
                    variant={
                      currentTenant?.role === 'OWNER'
                        ? 'purple'
                        : currentTenant?.role === 'ADMIN'
                        ? 'indigo'
                        : 'neutral'
                    }
                    size="sm"
                  >
                    {currentTenant?.role || 'MEMBER'}
                  </Badge>
                </div>
              </div>

              {/* Links */}
              <div className="py-1">
                <Link
                  to="/settings"
                  onClick={() => setUserMenuOpen(false)}
                  className="flex items-center gap-2.5 px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition"
                >
                  <Settings className="w-3.5 h-3.5 text-slate-400" />
                  <span>Workspace Settings & Members</span>
                </Link>

                <a
                  href="http://localhost:8000/api/v1/docs"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-between px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition"
                >
                  <span className="flex items-center gap-2.5">
                    <ExternalLink className="w-3.5 h-3.5 text-slate-400" />
                    <span>FastAPI OpenAPI Docs</span>
                  </span>
                  <span className="text-[10px] text-slate-400 font-mono">v0.2.0</span>
                </a>
              </div>

              {/* Sign out */}
              <div className="pt-1 border-t border-slate-100">
                <button
                  onClick={() => {
                    setUserMenuOpen(false);
                    logout();
                  }}
                  className="w-full flex items-center gap-2.5 px-4 py-2 text-xs font-medium text-rose-600 hover:bg-rose-50 transition"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  <span>Sign out of DocIntelligence</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
