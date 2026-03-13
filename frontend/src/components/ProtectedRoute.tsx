// MIT License -- see LICENSE-MIT
//
// ProtectedRoute wrapper -- redirects to /login when unauthenticated.

import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

function LoadingScreen() {
  return (
    <div className="flex h-screen items-center justify-center bg-gray-50">
      <div className="text-center">
        <div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-4 border-brand-200 border-t-brand-600" />
        <p className="text-sm text-gray-500">Loading...</p>
      </div>
    </div>
  );
}

export default function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <LoadingScreen />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
