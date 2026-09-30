import { Navigate, Outlet, Route, Routes } from 'react-router-dom';

import { PublicLayout } from '@/components/layout/PublicLayout';
import { DashboardLayout } from '@/components/layout/DashboardLayout';
import { ProtectedRoute } from '@/routes/ProtectedRoute';
import { RoleRoute } from '@/routes/RoleRoute';

import { ROLES } from '@/constants/roles';

// Public
import LandingPage from '@/pages/public/LandingPage';
import AboutPage from '@/pages/public/AboutPage';
import HowItWorksPage from '@/pages/public/HowItWorksPage';
import ContactPage from '@/pages/public/ContactPage';
import NotFoundPage from '@/pages/public/NotFoundPage';

// The customer's page — reached by scanning a package's QR code, no account needed
import TracePage from '@/pages/public/TracePage';

// Auth
import LoginPage from '@/pages/auth/LoginPage';
import RegisterPage from '@/pages/auth/RegisterPage';

// Shared authenticated screens
import DashboardPage from '@/pages/dashboard/DashboardPage';
import ProfilePage from '@/pages/profile/ProfilePage';
import ConsumerVerificationPage from '@/pages/consumer/ConsumerVerificationPage';

// Beekeeper
import BeekeeperDashboardPage from '@/pages/beekeeper/BeekeeperDashboardPage';
import BeekeeperProfilePage from '@/pages/beekeeper/BeekeeperProfilePage';
import BeekeeperTraceabilityPage from '@/pages/beekeeper/BeekeeperTraceabilityPage';
import MyHivesPage from '@/pages/beekeeper/MyHivesPage';
import HiveDetailPage from '@/pages/beekeeper/HiveDetailPage';
import IotMonitoringPage from '@/pages/beekeeper/IotMonitoringPage';
import AiInsightsPage from '@/pages/beekeeper/AiInsightsPage';
import AlertsPage from '@/pages/beekeeper/AlertsPage';

// Harvests and honey batches (shared by beekeeper, KVIC and admin screens)
import CollectionsPage from '@/pages/collections/CollectionsPage';
import CollectionDetailPage from '@/pages/collections/CollectionDetailPage';
import BatchesPage from '@/pages/collections/BatchesPage';
import BatchDetailPage from '@/pages/collections/BatchDetailPage';

// KVIC
import KvicDashboardPage from '@/pages/kvic/KvicDashboardPage';
import KvicBeekeepersPage from '@/pages/kvic/KvicBeekeepersPage';
import KvicClustersPage from '@/pages/kvic/KvicClustersPage';
import KvicClusterDetailPage from '@/pages/kvic/KvicClusterDetailPage';
import KvicHivesPage from '@/pages/kvic/KvicHivesPage';
import KvicIotPage from '@/pages/kvic/KvicIotPage';
import KvicInsightsPage from '@/pages/kvic/KvicInsightsPage';
import KvicAlertsPage from '@/pages/kvic/KvicAlertsPage';
import KvicProcessingPage from '@/pages/kvic/KvicProcessingPage';
import KvicLaboratoryPage from '@/pages/kvic/KvicLaboratoryPage';
import KvicTraceabilityPage from '@/pages/kvic/KvicTraceabilityPage';
import KvicClusterAnalyticsPage from '@/pages/kvic/KvicClusterAnalyticsPage';

// Administration
import AdminDashboardPage from '@/pages/admin/AdminDashboardPage';
import AdminUsersPage from '@/pages/admin/AdminUsersPage';
import AdminBeekeepersPage from '@/pages/admin/AdminBeekeepersPage';
import AdminClustersPage from '@/pages/admin/AdminClustersPage';
import AdminPackagingUnitsPage from '@/pages/admin/AdminPackagingUnitsPage';
import AdminClusterDetailPage from '@/pages/admin/AdminClusterDetailPage';
import AdminHivesPage from '@/pages/admin/AdminHivesPage';
import AdminIotPage from '@/pages/admin/AdminIotPage';
import AdminInsightsPage from '@/pages/admin/AdminInsightsPage';
import AdminAlertsPage from '@/pages/admin/AdminAlertsPage';
import AdminProcessingPage from '@/pages/admin/AdminProcessingPage';
import AdminLaboratoryPage from '@/pages/admin/AdminLaboratoryPage';
import AuditLogsPage from '@/pages/admin/AuditLogsPage';

// Traceability ledger (shared by an administrator and a KVIC officer; the
// backend narrows a KVIC officer to their own clusters)
import BlockchainLedgerPage from '@/pages/blockchain/BlockchainLedgerPage';

// Packaging (packaging unit)
import ApprovedBatchesPage from '@/pages/packaging/ApprovedBatchesPage';
import PackagingDashboardPage from '@/pages/packaging/PackagingDashboardPage';
import PackagingHistoryPage from '@/pages/packaging/PackagingHistoryPage';
import PackagingInformationPage from '@/pages/packaging/PackagingInformationPage';
import PackageInformationPage from '@/pages/packaging/PackageInformationPage';
import PackagingRunsPage from '@/pages/packaging/PackagingRunsPage';
import PackedStockPage from '@/pages/packaging/PackedStockPage';
import QrGenerationPage from '@/pages/packaging/QrGenerationPage';

// Distribution and retail
import DistributorWorkspacePage from '@/pages/distribution/DistributorWorkspacePage';
import RetailerWorkspacePage from '@/pages/distribution/RetailerWorkspacePage';

// Laboratory (lab technician)
import LaboratoryWorkspacePage from '@/pages/laboratory/LaboratoryWorkspacePage';
import LabTestDetailPage from '@/pages/laboratory/LabTestDetailPage';
import ParameterCataloguePage from '@/pages/laboratory/ParameterCataloguePage';
import FacilitiesPage from '@/pages/laboratory/FacilitiesPage';

// Processing (processor)
import ProcessorWorkspacePage from '@/pages/processing/ProcessorWorkspacePage';
import ProcessingRunDetailPage from '@/pages/processing/ProcessingRunDetailPage';

/**
 * Route table.
 *
 * Each role owns a subtree, and the subtree is wrapped in a single `RoleRoute`.
 * That guard does two things: it checks the role the screen was written for, and it
 * checks the path against the central navigation configuration — so a URL typed by
 * hand is refused exactly like a link that was never rendered, and the user is
 * returned to their own workspace instead of being shown a notice about someone
 * else's.
 *
 * There are no placeholder routes. Everything listed here is a working screen;
 * modules that are not built are described on the dashboards, not routed.
 */
export function AppRoutes() {
  return (
    <Routes>
      {/* Public marketing site */}
      <Route element={<PublicLayout />}>
        <Route index element={<LandingPage />} />
        <Route path="about" element={<AboutPage />} />
        <Route path="how-it-works" element={<HowItWorksPage />} />
        <Route path="contact" element={<ContactPage />} />
      </Route>

      {/* The customer's traceability page: a QR code resolves here, and the
          person holding the jar is not asked to sign in. */}
      <Route path="trace/:packageCode" element={<TracePage />} />
      {/* The QR id printed beside the code on the label resolves here too. */}
      <Route path="verify/:code" element={<TracePage />} />

      {/* Authentication */}
      <Route path="login" element={<LoginPage />} />
      <Route path="register" element={<RegisterPage />} />

      {/* Authenticated application */}
      <Route element={<ProtectedRoute />}>
        <Route element={<DashboardLayout />}>
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="profile" element={<ProfilePage />} />

          {/* ---------------------------------------------------- Beekeeper */}
          <Route
            path="beekeeper"
            element={
              <RoleRoute allow={[ROLES.BEEKEEPER]}>
                <Outlet />
              </RoleRoute>
            }
          >
            <Route index element={<BeekeeperDashboardPage />} />
            <Route path="profile" element={<BeekeeperProfilePage />} />
            <Route path="hives" element={<MyHivesPage />} />
            <Route path="hives/:hiveId" element={<HiveDetailPage />} />
            <Route path="iot" element={<IotMonitoringPage />} />
            <Route path="insights" element={<AiInsightsPage />} />
            <Route path="alerts" element={<AlertsPage />} />
            <Route path="collections" element={<CollectionsPage />} />
            <Route path="collections/:collectionId" element={<CollectionDetailPage />} />
            <Route path="batches" element={<BatchesPage />} />
            <Route path="batches/:batchId" element={<BatchDetailPage />} />
            <Route path="traceability" element={<BeekeeperTraceabilityPage />} />
            <Route path="traceability/:batchId" element={<BeekeeperTraceabilityPage />} />
          </Route>

          {/* --------------------------------------------------------- KVIC */}
          <Route
            path="kvic"
            element={
              <RoleRoute allow={[ROLES.KVIC_OFFICER, ROLES.ADMIN]}>
                <Outlet />
              </RoleRoute>
            }
          >
            <Route index element={<KvicDashboardPage />} />
            <Route path="beekeepers" element={<KvicBeekeepersPage />} />
            <Route path="clusters" element={<KvicClustersPage />} />
            <Route path="clusters/:clusterId" element={<KvicClusterDetailPage />} />
            <Route path="hives" element={<KvicHivesPage />} />
            <Route path="hives/:hiveId" element={<HiveDetailPage />} />
            <Route path="iot" element={<KvicIotPage />} />
            <Route path="insights" element={<KvicInsightsPage />} />
            <Route path="alerts" element={<KvicAlertsPage />} />
            <Route path="collections" element={<CollectionsPage />} />
            <Route path="collections/:collectionId" element={<CollectionDetailPage />} />
            <Route path="batches" element={<BatchesPage />} />
            <Route path="batches/:batchId" element={<BatchDetailPage />} />
            <Route path="processing" element={<KvicProcessingPage />} />
            <Route path="processing/runs/:processingId" element={<ProcessingRunDetailPage basePath="/kvic/processing" />} />
            <Route path="laboratory" element={<KvicLaboratoryPage />} />
            <Route path="laboratory/tests/:testId" element={<LabTestDetailPage />} />
            <Route path="traceability" element={<KvicTraceabilityPage />} />
            <Route path="traceability/:batchId" element={<KvicTraceabilityPage />} />
            <Route path="cluster-analytics" element={<KvicClusterAnalyticsPage />} />
            <Route path="blockchain" element={<BlockchainLedgerPage />} />
          </Route>

          {/* ---------------------------------------------------- Laboratory */}
          <Route
            path="laboratory"
            element={
              <RoleRoute allow={[ROLES.LAB_TECHNICIAN]}>
                <Outlet />
              </RoleRoute>
            }
          >
            <Route index element={<LaboratoryWorkspacePage view="overview" />} />
            {/* Each queue is its own screen; the batch-level "awaiting a sample" list
                is the one that shows the seam with the processing workspace. */}
            <Route path="pending" element={<LaboratoryWorkspacePage view="pending" />} />
            <Route path="assigned" element={<LaboratoryWorkspacePage view="assigned" />} />
            <Route path="awaiting" element={<LaboratoryWorkspacePage view="awaiting" />} />
            <Route path="completed" element={<LaboratoryWorkspacePage view="completed" />} />
            <Route path="held" element={<LaboratoryWorkspacePage view="held" />} />
            <Route path="tests" element={<LaboratoryWorkspacePage view="tests" />} />
            <Route path="tests/completed" element={<LaboratoryWorkspacePage view="completed" />} />
            <Route path="tests/:testId" element={<LabTestDetailPage />} />
            <Route path="samples" element={<LaboratoryWorkspacePage view="samples" />} />
            <Route path="parameters" element={<ParameterCataloguePage />} />
            <Route path="facilities" element={<FacilitiesPage />} />
          </Route>

          {/* ----------------------------------------------------- Processor */}
          <Route
            path="processor"
            element={
              <RoleRoute allow={[ROLES.PROCESSOR, ROLES.ADMIN]}>
                <Outlet />
              </RoleRoute>
            }
          >
            <Route index element={<ProcessorWorkspacePage view="overview" />} />
            {/* The queues the prompt names, each a screen of its own. */}
            <Route path="pending" element={<ProcessorWorkspacePage view="pending" />} />
            <Route path="assigned" element={<ProcessorWorkspacePage view="assigned" />} />
            <Route path="processing" element={<ProcessorWorkspacePage view="processing" />} />
            <Route path="completed" element={<ProcessorWorkspacePage view="completed" />} />
            <Route path="history" element={<ProcessorWorkspacePage view="history" />} />
            <Route path="awaiting" element={<ProcessorWorkspacePage view="awaiting" />} />
            <Route path="runs" element={<ProcessorWorkspacePage view="runs" />} />
            <Route path="runs/:processingId" element={<ProcessingRunDetailPage basePath="/processor" />} />
            <Route path="batches" element={<BatchesPage />} />
            <Route path="batches/:batchId" element={<BatchDetailPage />} />
            <Route path="units" element={<ProcessorWorkspacePage view="units" />} />
          </Route>

          {/* ------------------------------------------------- Administration */}
          <Route
            path="admin"
            element={
              <RoleRoute allow={[ROLES.ADMIN]}>
                <Outlet />
              </RoleRoute>
            }
          >
            <Route index element={<AdminDashboardPage />} />
            <Route path="users" element={<AdminUsersPage />} />
            <Route path="beekeepers" element={<AdminBeekeepersPage />} />
            <Route path="clusters" element={<AdminClustersPage />} />
            <Route path="clusters/:clusterId" element={<AdminClusterDetailPage />} />
            {/* The register of packaging facilities. Administrator-only: a unit is
                commissioned by an administrator, never through public sign-up. */}
            <Route path="packaging-units" element={<AdminPackagingUnitsPage />} />
            <Route path="hives" element={<AdminHivesPage />} />
            <Route path="hives/:hiveId" element={<HiveDetailPage />} />
            <Route path="iot" element={<AdminIotPage />} />
            <Route path="insights" element={<AdminInsightsPage />} />
            <Route path="alerts" element={<AdminAlertsPage />} />
            <Route path="collections" element={<CollectionsPage />} />
            <Route path="collections/:collectionId" element={<CollectionDetailPage />} />
            <Route path="batches" element={<BatchesPage />} />
            <Route path="batches/:batchId" element={<BatchDetailPage />} />
            <Route path="processing" element={<AdminProcessingPage />} />
            <Route path="processing/runs/:processingId" element={<ProcessingRunDetailPage basePath="/admin/processing" />} />
            <Route path="laboratory" element={<AdminLaboratoryPage />} />
            <Route path="laboratory/tests/:testId" element={<LabTestDetailPage />} />
            <Route path="laboratory/parameters" element={<ParameterCataloguePage />} />
            <Route path="audit-logs" element={<AuditLogsPage />} />
            <Route path="blockchain" element={<BlockchainLedgerPage />} />
          </Route>

          {/* ----------------------------------------------- Packaging unit */}
          <Route
            path="packaging"
            element={
              <RoleRoute allow={[ROLES.PACKAGING_UNIT]}>
                <Outlet />
              </RoleRoute>
            }
          >
            <Route index element={<PackagingDashboardPage />} />
            <Route path="approved" element={<ApprovedBatchesPage />} />
            <Route path="runs" element={<PackagingRunsPage />} />
            <Route path="runs/:packagingId" element={<PackagingInformationPage />} />
            <Route path="stock" element={<PackedStockPage />} />
            <Route path="qr" element={<QrGenerationPage />} />
            <Route path="packages/:packageId" element={<PackageInformationPage />} />
            <Route path="history" element={<PackagingHistoryPage />} />
          </Route>

          {/* --------------------------------------------------- Distribution */}
          <Route
            path="distributor"
            element={
              <RoleRoute allow={[ROLES.DISTRIBUTOR]}>
                <Outlet />
              </RoleRoute>
            }
          >
            <Route index element={<DistributorWorkspacePage />} />
            <Route path="ready" element={<DistributorWorkspacePage view="ready" />} />
            <Route path="shipments" element={<DistributorWorkspacePage view="shipments" />} />
            <Route path="transit" element={<DistributorWorkspacePage view="transit" />} />
            <Route path="delivered" element={<DistributorWorkspacePage view="delivered" />} />
          </Route>

          {/* --------------------------------------------------------- Retail */}
          <Route
            path="retailer"
            element={
              <RoleRoute allow={[ROLES.RETAILER]}>
                <Outlet />
              </RoleRoute>
            }
          >
            <Route index element={<RetailerWorkspacePage />} />
            <Route path="inbound" element={<RetailerWorkspacePage view="inbound" />} />
            <Route path="received" element={<RetailerWorkspacePage view="received" />} />
          </Route>

          {/* -------------------------------------------- Collection centre */}
          <Route
            path="collection-center"
            element={
              <RoleRoute allow={[ROLES.COLLECTION_CENTER]}>
                <Outlet />
              </RoleRoute>
            }
          >
            <Route index element={<CollectionsPage />} />
            <Route path="collections/:collectionId" element={<CollectionDetailPage />} />
          </Route>
          {/* The consumer's workspace: a real verification screen. The public
              page it reads from (/trace/:code, /verify/:code) needs no account;
              this route is the same record for a person who is signed in. */}
          <Route
            path="consumer"
            element={
              <RoleRoute allow={[ROLES.CONSUMER]}>
                <ConsumerVerificationPage />
              </RoleRoute>
            }
          />
        </Route>
      </Route>

      {/* Aliases */}
      <Route path="home" element={<Navigate to="/" replace />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

export default AppRoutes;
