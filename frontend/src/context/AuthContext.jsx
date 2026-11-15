import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from 'react';
import { authApi, configureApiAuth, setApiAccessToken } from '../services/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [tenants, setTenants] = useState([]);
  const [currentTenant, setCurrentTenant] = useState(null);
  const [accessToken, setAccessToken] = useState(() => sessionStorage.getItem('access_token'));
  const [loading, setLoading] = useState(true);

  const tokenRef = useRef(accessToken);
  tokenRef.current = accessToken;
  const tenantRef = useRef(currentTenant);
  tenantRef.current = currentTenant;

  // Sync callbacks with Axios interceptors
  useEffect(() => {
    if (accessToken) {
      sessionStorage.setItem('access_token', accessToken);
      setApiAccessToken(accessToken);
    } else {
      sessionStorage.removeItem('access_token');
      setApiAccessToken(null);
    }

    configureApiAuth({
      getAccessToken: () => tokenRef.current || sessionStorage.getItem('access_token'),
      getActiveTenantId: () => tenantRef.current?.tenant_id || tenantRef.current?.id || sessionStorage.getItem('active_tenant_id') || null,
      onTokenRefreshed: (newToken) => {
        tokenRef.current = newToken;
        setApiAccessToken(newToken);
        setAccessToken(newToken);
        if (newToken) sessionStorage.setItem('access_token', newToken);
      },
      onAuthFailed: () => {
        tokenRef.current = null;
        setApiAccessToken(null);
        setAccessToken(null);
        setUser(null);
        setCurrentTenant(null);
        setTenants([]);
        sessionStorage.removeItem('access_token');
        sessionStorage.removeItem('active_tenant_id');
      },
    });
  }, [accessToken, currentTenant]);

  // Load user profile and memberships
  const loadUserProfile = useCallback(async () => {
    try {
      const res = await authApi.getMe();
      const userData = res.data;
      setUser({
        id: userData.id,
        email: userData.email,
        full_name: userData.full_name,
        is_active: userData.is_active,
      });

      const memberTenants = userData.memberships || [];
      setTenants(memberTenants);

      // Restore previously selected tenant or default to first
      const savedTenantId = sessionStorage.getItem('active_tenant_id');
      const matched = memberTenants.find((t) => t.tenant_id === savedTenantId);
      if (matched) {
        setCurrentTenant(matched);
      } else if (memberTenants.length > 0) {
        setCurrentTenant(memberTenants[0]);
        sessionStorage.setItem('active_tenant_id', memberTenants[0].tenant_id);
      }
    } catch (err) {
      console.warn('[Auth] Failed to load profile:', err.message);
    }
  }, []);

  // Attempt initial session restore via sessionStorage or HttpOnly refresh cookie on application load
  useEffect(() => {
    let isMounted = true;
    const initializeAuth = async () => {
      try {
        const savedToken = sessionStorage.getItem('access_token');
        if (savedToken) {
          setAccessToken(savedToken);
          // Wait for user profile before clearing loading indicator
          await loadUserProfile();
        } else {
          const refreshRes = await authApi.refresh();
          if (isMounted && refreshRes.data?.access_token) {
            setAccessToken(refreshRes.data.access_token);
            await loadUserProfile();
          }
        }
      } catch (err) {
        // No active session cookie or invalid token found
        sessionStorage.removeItem('access_token');
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    initializeAuth();
    return () => {
      isMounted = false;
    };
  }, [loadUserProfile]);

  // When access token becomes available, load user profile
  useEffect(() => {
    if (accessToken) {
      loadUserProfile();
    }
  }, [accessToken, loadUserProfile]);

  const login = async (email, password) => {
    const res = await authApi.login({ email, password });
    const { access_token, user: resUser, organization, role } = res.data;
    setAccessToken(access_token);
    setUser(resUser);

    if (organization) {
      const initialTenant = {
        tenant_id: organization.id,
        tenant_name: organization.name,
        tenant_slug: organization.slug,
        role: role || 'OWNER',
      };
      setCurrentTenant(initialTenant);
      sessionStorage.setItem('active_tenant_id', organization.id);
    }
    await loadUserProfile();
    return res.data;
  };

  const register = async (fullName, email, password, organizationName) => {
    const res = await authApi.register({
      full_name: fullName,
      email,
      password,
      organization_name: organizationName,
    });
    const { access_token, user: resUser, organization, role } = res.data;
    setAccessToken(access_token);
    setUser(resUser);

    if (organization) {
      const initialTenant = {
        tenant_id: organization.id,
        tenant_name: organization.name,
        tenant_slug: organization.slug,
        role: role || 'OWNER',
      };
      setCurrentTenant(initialTenant);
      sessionStorage.setItem('active_tenant_id', organization.id);
    }
    await loadUserProfile();
    return res.data;
  };

  const logout = async () => {
    try {
      await authApi.logout();
    } catch (err) {
      // Ignore network errors on logout
    } finally {
      setAccessToken(null);
      setUser(null);
      setCurrentTenant(null);
      setTenants([]);
      sessionStorage.removeItem('active_tenant_id');
    }
  };

  const switchTenant = (tenantId) => {
    const selected = tenants.find((t) => t.tenant_id === tenantId);
    if (selected) {
      setCurrentTenant(selected);
      sessionStorage.setItem('active_tenant_id', tenantId);
    }
  };

  const value = {
    user,
    tenants,
    currentTenant,
    accessToken,
    isAuthenticated: Boolean(accessToken && user),
    loading,
    login,
    register,
    logout,
    switchTenant,
    refreshProfile: loadUserProfile,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
