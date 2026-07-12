import { useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { AppLayout } from "./components/AppLayout";
import { ToastProvider } from "./components/Toast";
import { AnnotationPage } from "./pages/AnnotationPage";
import { CasesPage } from "./pages/CasesPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ExportPage } from "./pages/ExportPage";
import { InferencePage } from "./pages/InferencePage";
import { QualityPage } from "./pages/QualityPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TrainPage } from "./pages/TrainPage";
import { VersionsPage } from "./pages/VersionsPage";

export default function App() {
  const [refreshKey, setRefreshKey] = useState(0);
  const bump = () => setRefreshKey((value) => value + 1);

  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout onRefresh={bump} />}>
              <Route index element={<DashboardPage refreshKey={refreshKey} />} />
              <Route path="cases" element={<CasesPage refreshKey={refreshKey} />} />
              <Route path="annotation" element={<AnnotationPage refreshKey={refreshKey} />} />
              <Route path="annotation/:caseId" element={<AnnotationPage refreshKey={refreshKey} />} />
              <Route path="train" element={<TrainPage refreshKey={refreshKey} />} />
              <Route path="inference" element={<InferencePage refreshKey={refreshKey} />} />
              <Route path="versions" element={<VersionsPage refreshKey={refreshKey} />} />
              <Route path="versions/:caseId" element={<VersionsPage refreshKey={refreshKey} />} />
              <Route path="quality" element={<QualityPage refreshKey={refreshKey} />} />
              <Route path="export" element={<ExportPage refreshKey={refreshKey} />} />
              <Route path="settings" element={<SettingsPage refreshKey={refreshKey} />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  );
}
