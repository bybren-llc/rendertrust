// MIT License -- see LICENSE-MIT
import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";
import DashboardPage from "./pages/DashboardPage";
import JobListPage from "./pages/jobs/JobListPage";
import SubmitJobPage from "./pages/jobs/SubmitJobPage";
import JobDetailPage from "./pages/jobs/JobDetailPage";
import CreditsPage from "./pages/CreditsPage";
import SettingsPage from "./pages/SettingsPage";
import LoginPage from "./pages/auth/LoginPage";
import RegisterPage from "./pages/auth/RegisterPage";

function App() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      {/* Protected routes -- redirect to /login when unauthenticated */}
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/jobs" element={<JobListPage />} />
          <Route path="/jobs/new" element={<SubmitJobPage />} />
          <Route path="/jobs/:id" element={<JobDetailPage />} />
          <Route path="/credits" element={<CreditsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>
    </Routes>
  );
}

export default App;
